import os
import re
from fnmatch import translate

from conans import load
from conans.errors import NotFoundException, ConanException, ForbiddenException, \
    RecipeNotFoundException
from conans.model.info import ConanInfo
from conans.model.ref import PackageReference, ConanFileReference
from conans.paths import CONANINFO
from conans.search.search import filter_packages, _partial_match
from conans.util.files import list_folder_subdirs
from conans.util.log import logger


def _get_local_infos_min(server_store, ref, look_in_all_rrevs):

    result = {}
    rrevs = server_store.get_recipe_revisions(ref) if look_in_all_rrevs else [None]

    for rrev in rrevs:
        new_ref = ref.copy_with_rev(rrev.revision) if rrev else ref
        subdirs = list_folder_subdirs(server_store.packages(new_ref), level=1)
        for package_id in subdirs:
            if package_id in result:
                continue
            # Read conaninfo
            try:
                pref = PackageReference(new_ref, package_id)
                revision_entry = server_store.get_last_package_revision(pref)
                if not revision_entry:
                    raise NotFoundException("")
                pref = PackageReference(new_ref, package_id, revision_entry.revision)
                info_path = os.path.join(server_store.package(pref), CONANINFO)
                if not os.path.exists(info_path):
                    raise NotFoundException("")
                conan_info_content = load(info_path)
                info = ConanInfo.loads(conan_info_content)
                conan_vars_info = info.serialize_min()
                result[package_id] = conan_vars_info
            except Exception as exc:  # FIXME: Too wide
                logger.error("Package %s has no ConanInfo file" % str(pref))
                if str(exc):
                    logger.error(str(exc))
    return result


def search_packages(server_store, ref, query, look_in_all_rrevs):
    """
    Used both for v1 and v2. V1 will iterate rrevs.

    Return a dict like this:

            {package_ID: {name: "OpenCV",
                           version: "2.14",
                           settings: {os: Windows}}}
    param ref: ConanFileReference object
    """
    if not look_in_all_rrevs and ref.revision is None:
        latest_rev = server_store.get_last_revision(ref).revision
        ref = ref.copy_with_rev(latest_rev)

    if not os.path.exists(server_store.conan_revisions_root(ref.copy_clear_rev())):
        raise RecipeNotFoundException(ref)
    infos = _get_local_infos_min(server_store, ref, look_in_all_rrevs)
    return filter_packages(query, infos)


class SearchService(object):

    def __init__(self, authorizer, server_store, auth_user):
        self._authorizer = authorizer
        self._server_store = server_store
        self._auth_user = auth_user

    def search_packages(self, reference, query, look_in_all_rrevs=False):
        """Shared between v1 and v2, v1 will iterate rrevs"""
        self._authorizer.check_read_conan(self._auth_user, reference)
        info = search_packages(self._server_store, reference, query, look_in_all_rrevs)
        return info

    def _search_recipes(self, pattern=None, ignorecase=True):

        def get_ref(_pattern):
            if not isinstance(_pattern, ConanFileReference):
                try:
                    ref_ = ConanFileReference.loads(_pattern)
                except (ConanException, TypeError):
                    ref_ = None
            else:
                ref_ = _pattern
            return ref_

        # Conan references in main storage
        if pattern:
            pattern = str(pattern)
            b_pattern = translate(pattern)
            b_pattern = re.compile(b_pattern, re.IGNORECASE) \
                if ignorecase else re.compile(b_pattern)

        subdirs = list_folder_subdirs(basedir=self._server_store.store, level=5)
        if not pattern:
            return sorted([ConanFileReference(*folder.split("/")) for folder in subdirs])
        else:
            ret = set()
            for subdir in subdirs:
                new_ref = ConanFileReference(*subdir.split("/"))
                if _partial_match(b_pattern, new_ref.full_repr()):
                    ret.add(new_ref.copy_clear_rev())

            return sorted(ret)

    def search(self, pattern=None, ignorecase=True):
        """ Get all the info about any package
            Attributes:
                pattern = wildcards like opencv/*
        """
        refs = self._search_recipes(pattern, ignorecase)
        filtered = []
        # Filter out restricted items
        for ref in refs:
            try:
                self._authorizer.check_read_conan(self._auth_user, ref)
                filtered.append(ref)
            except ForbiddenException:
                pass
        return filtered
