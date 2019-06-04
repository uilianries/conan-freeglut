from conans.client.output import ScopedOutput
from conans.client.source import complete_recipe_sources
from conans.model.ref import ConanFileReference, PackageReference


def download(ref, package_ids, remote, recipe, remote_manager,
             cache, out, recorder, loader, hook_manager, remotes):

    assert(isinstance(ref, ConanFileReference))
    output = ScopedOutput(str(ref), out)

    hook_manager.execute("pre_download", reference=ref, remote=remote)

    ref = remote_manager.get_recipe(ref, remote)
    with cache.package_layout(ref).update_metadata() as metadata:
        metadata.recipe.remote = remote.name

    conan_file_path = cache.package_layout(ref).conanfile()
    conanfile = loader.load_class(conan_file_path)

    # Download the sources too, don't be lazy
    complete_recipe_sources(remote_manager, cache, conanfile, ref, remotes)

    if not recipe:  # Not only the recipe
        if not package_ids:  # User didn't specify a specific package binary
            output.info("Getting the complete package list from '%s'..." % ref.full_repr())
            packages_props = remote_manager.search_packages(remote, ref, None)
            package_ids = list(packages_props.keys())
            if not package_ids:
                output.warn("No remote binary packages found in remote")

        _download_binaries(conanfile, ref, package_ids, cache, remote_manager,
                           remote, output, recorder)
    hook_manager.execute("post_download", conanfile_path=conan_file_path, reference=ref,
                         remote=remote)


def _download_binaries(conanfile, ref, package_ids, cache, remote_manager, remote, output,
                       recorder):
    short_paths = conanfile.short_paths

    for package_id in package_ids:
        pref = PackageReference(ref, package_id)
        package_folder = cache.package_layout(pref.ref, short_paths=short_paths).package(pref)
        output.info("Downloading %s" % str(pref))
        remote_manager.get_package(pref, package_folder, remote, output, recorder)
