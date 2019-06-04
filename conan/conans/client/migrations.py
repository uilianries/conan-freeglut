import os
import shutil

from conans import DEFAULT_REVISION_V1
from conans.client import migrations_settings
from conans.client.cache.cache import CONAN_CONF, PROFILES_FOLDER
from conans.client.conf.config_installer import _ConfigOrigin, _save_configs
from conans.client.tools import replace_in_file
from conans.errors import ConanException
from conans.migrations import Migrator
from conans.model.manifest import FileTreeManifest
from conans.model.package_metadata import PackageMetadata
from conans.model.ref import ConanFileReference, PackageReference
from conans.model.version import Version
from conans.paths import EXPORT_SOURCES_DIR_OLD
from conans.paths import PACKAGE_METADATA
from conans.paths.package_layouts.package_cache_layout import PackageCacheLayout
from conans.util.files import list_folder_subdirs, load, save
from conans.client.cache.remote_registry import migrate_registry_file


class ClientMigrator(Migrator):

    def __init__(self, cache, current_version, out):
        self.cache = cache
        super(ClientMigrator, self).__init__(cache.cache_folder, cache.store,
                                             current_version, out)

    def _update_settings_yml(self, old_version):

        from conans.client.conf import default_settings_yml
        settings_path = self.cache.settings_path
        if not os.path.exists(settings_path):
            self.out.warn("Migration: This conan installation doesn't have settings yet")
            self.out.warn("Nothing to migrate here, settings will be generated automatically")
            return

        var_name = "settings_{}".format(old_version.replace(".", "_"))

        def save_new():
            new_path = self.cache.settings_path + ".new"
            save(new_path, default_settings_yml)
            self.out.warn("*" * 40)
            self.out.warn("settings.yml is locally modified, can't be updated")
            self.out.warn("The new settings.yml has been stored in: %s" % new_path)
            self.out.warn("*" * 40)

        self.out.warn("Migration: Updating settings.yml")
        if hasattr(migrations_settings, var_name):
            version_default_contents = getattr(migrations_settings, var_name)
            if version_default_contents != default_settings_yml:
                current_settings = load(self.cache.settings_path)
                if current_settings != version_default_contents:
                    save_new()
                else:
                    save(self.cache.settings_path, default_settings_yml)
            else:
                self.out.info("Migration: Settings already up to date")
        else:
            # We don't have the value for that version, so don't override
            save_new()

    def _make_migrations(self, old_version):
        # ############### FILL THIS METHOD WITH THE REQUIRED ACTIONS ##############
        # VERSION 0.1
        if old_version is None:
            return

        # Migrate the settings if they were the default for that version
        self._update_settings_yml(old_version)

        if old_version < Version("0.25"):
            from conans.paths import DEFAULT_PROFILE_NAME
            default_profile_path = os.path.join(self.cache.cache_folder, PROFILES_FOLDER,
                                                DEFAULT_PROFILE_NAME)
            if not os.path.exists(default_profile_path):
                self.out.warn("Migration: Moving default settings from %s file to %s"
                              % (CONAN_CONF, DEFAULT_PROFILE_NAME))
                conf_path = os.path.join(self.cache.cache_folder, CONAN_CONF)

                migrate_to_default_profile(conf_path, default_profile_path)

                self.out.warn("Migration: export_source cache new layout")
                migrate_c_src_export_source(self.cache, self.out)

        if old_version < Version("1.0"):
            _migrate_lock_files(self.cache, self.out)

        if old_version < Version("1.12.0"):
            migrate_plugins_to_hooks(self.cache)

        if old_version < Version("1.13.0"):
            # MIGRATE LOCAL CACHE TO GENERATE MISSING METADATA.json
            _migrate_create_metadata(self.cache, self.out)

        if old_version < Version("1.14.0"):
            migrate_config_install(self.cache)

        if old_version < Version("1.14.2"):
            _migrate_full_metadata(self.cache, self.out)

        if old_version < Version("1.15.0"):
            migrate_registry_file(self.cache, self.out)


def _get_refs(cache):
    folders = list_folder_subdirs(cache.store, 4)
    return [ConanFileReference(*s.split("/")) for s in folders]


def _get_prefs(layout):
    packages_folder = layout.packages()
    folders = list_folder_subdirs(packages_folder, 1)
    return [PackageReference(layout.ref, s) for s in folders]


def _migrate_full_metadata(cache, out):
    # Fix for https://github.com/conan-io/conan/issues/4898
    out.warn("Running a full revision metadata migration")
    refs = _get_refs(cache)
    for ref in refs:
        try:
            base_folder = os.path.normpath(os.path.join(cache.store, ref.dir_repr()))
            layout = PackageCacheLayout(base_folder=base_folder, ref=ref, short_paths=None,
                                        no_lock=True)
            with layout.update_metadata() as metadata:
                # Updating the RREV
                if metadata.recipe.revision is None:
                    out.warn("Package %s metadata had recipe revision None, migrating" % str(ref))
                    folder = layout.export()
                    try:
                        manifest = FileTreeManifest.load(folder)
                        rrev = manifest.summary_hash
                    except Exception:
                        rrev = DEFAULT_REVISION_V1
                    metadata.recipe.revision = rrev

                prefs = _get_prefs(layout)
                existing_ids = [pref.id for pref in prefs]
                for pkg_id in list(metadata.packages.keys()):
                    if pkg_id not in existing_ids:
                        out.warn("Package %s metadata had stalled package information %s, removing"
                                 % (str(ref), pkg_id))
                        del metadata.packages[pkg_id]
                # UPDATING PREVS
                for pref in prefs:
                    try:
                        pmanifest = FileTreeManifest.load(layout.package(pref))
                        prev = pmanifest.summary_hash
                    except Exception:
                        prev = DEFAULT_REVISION_V1
                    metadata.packages[pref.id].revision = prev
                    metadata.packages[pref.id].recipe_revision = metadata.recipe.revision

        except Exception as e:
            raise ConanException("Something went wrong while migrating metadata.json files "
                                 "in the cache, please try to fix the issue or wipe the cache: {}"
                                 ":{}".format(ref, e))


def _migrate_create_metadata(cache, out):
    out.warn("Migration: Generating missing metadata files")
    refs = _get_refs(cache)

    for ref in refs:
        try:
            base_folder = os.path.normpath(os.path.join(cache.store, ref.dir_repr()))
            # Force using a package cache layout for everything, we want to alter the cache,
            # not the editables
            layout = PackageCacheLayout(base_folder=base_folder, ref=ref, short_paths=False,
                                        no_lock=True)
            folder = layout.export()
            try:
                manifest = FileTreeManifest.load(folder)
                rrev = manifest.summary_hash
            except Exception:
                rrev = DEFAULT_REVISION_V1
            metadata_path = layout.package_metadata()
            if not os.path.exists(metadata_path):
                out.info("Creating {} for {}".format(PACKAGE_METADATA, ref))
                prefs = _get_prefs(layout)
                metadata = PackageMetadata()
                metadata.recipe.revision = rrev
                for pref in prefs:
                    try:
                        pmanifest = FileTreeManifest.load(layout.package(pref))
                        prev = pmanifest.summary_hash
                    except Exception:
                        prev = DEFAULT_REVISION_V1
                    metadata.packages[pref.id].revision = prev
                    metadata.packages[pref.id].recipe_revision = metadata.recipe.revision
                save(metadata_path, metadata.dumps())
        except Exception as e:
            raise ConanException("Something went wrong while generating the metadata.json files "
                                 "in the cache, please try to fix the issue or wipe the cache: {}"
                                 ":{}".format(ref, e))
    out.success("Migration: Generating missing metadata files finished OK!\n")


def _migrate_lock_files(cache, out):
    out.warn("Migration: Removing old lock files")
    base_dir = cache.store
    pkgs = list_folder_subdirs(base_dir, 4)
    for pkg in pkgs:
        out.info("Removing locks for %s" % pkg)
        try:
            count = os.path.join(base_dir, pkg, "rw.count")
            if os.path.exists(count):
                os.remove(count)
            count = os.path.join(base_dir, pkg, "rw.count.lock")
            if os.path.exists(count):
                os.remove(count)
            locks = os.path.join(base_dir, pkg, "locks")
            if os.path.exists(locks):
                shutil.rmtree(locks)
        except Exception as e:
            raise ConanException("Something went wrong while removing %s locks\n"
                                 "Error: %s\n"
                                 "Please clean your local conan cache manually"
                                 % (pkg, str(e)))
    out.warn("Migration: Removing old lock files finished\n")


def migrate_config_install(cache):
    try:
        item = cache.config.get_item("general.config_install")
        items = [r.strip() for r in item.split(",")]
        if len(items) == 4:
            config_type, uri, verify_ssl, args = items
        elif len(items) == 1:
            uri = items[0]
            verify_ssl = "True"
            args = "None"
            config_type = None
        else:
            raise Exception("I don't know how to migrate this config install: %s" % items)
        verify_ssl = "true" in verify_ssl.lower()
        args = None if "none" in args.lower() else args
        config = _ConfigOrigin.from_item(uri, config_type, verify_ssl, args, None, None)
        _save_configs(cache.config_install_file, [config])
        cache.config.rm_item("general.config_install")
    except ConanException:
        pass


def migrate_to_default_profile(conf_path, default_profile_path):
    tag = "[settings_defaults]"
    old_conf = load(conf_path)
    if tag not in old_conf:
        return
    tmp = old_conf.find(tag)
    new_conf = old_conf[0:tmp]
    rest = old_conf[tmp + len(tag):]
    if tmp:
        if "]" in rest:  # More sections after the settings_defaults
            new_conf += rest[rest.find("["):]
            save(conf_path, new_conf)
            settings = rest[:rest.find("[")].strip()
        else:
            save(conf_path, new_conf)
            settings = rest.strip()
        # Now generate the default profile from the read settings_defaults
        new_profile = "[settings]\n%s" % settings
        save(default_profile_path, new_profile)


def migrate_c_src_export_source(cache, out):
    package_folders = list_folder_subdirs(cache.store, 4)
    for package in package_folders:
        package_folder = os.path.join(cache.store, package)
        c_src = os.path.join(package_folder, "export/%s" % EXPORT_SOURCES_DIR_OLD)
        if os.path.exists(c_src):
            out.warn("Migration: Removing package with old export_sources layout: %s" % package)
            try:
                shutil.rmtree(package_folder)
            except Exception:
                out.warn("Migration: Can't remove the '%s' directory, "
                         "remove it manually" % package_folder)


def migrate_plugins_to_hooks(cache, output=None):
    plugins_path = os.path.join(cache.cache_folder, "plugins")
    if os.path.exists(plugins_path) and not os.path.exists(cache.hooks_path):
        os.rename(plugins_path, cache.hooks_path)
    conf_path = cache.conan_conf_path
    replace_in_file(conf_path, "[plugins]", "[hooks]", strict=False, output=output)
