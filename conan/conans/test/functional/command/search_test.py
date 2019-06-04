import json
import os
import shutil
import textwrap
import time
import unittest
from collections import OrderedDict

from mock import patch

from conans import COMPLEX_SEARCH_CAPABILITY, DEFAULT_REVISION_V1
from conans.model.manifest import FileTreeManifest
from conans.model.package_metadata import PackageMetadata
from conans.model.ref import ConanFileReference, PackageReference
from conans.paths import CONANINFO, EXPORT_FOLDER, PACKAGES_FOLDER
from conans.server.revision_list import RevisionList
from conans.test.utils.tools import TestClient, TestServer, NO_SETTINGS_PACKAGE_ID
from conans.util.dates import iso8601_to_str, from_timestamp_to_iso8601
from conans.util.env_reader import get_env
from conans.util.files import list_folder_subdirs, load
from conans.util.files import save

conan_vars1 = '''
[settings]
    arch=x64
    os=Windows
    compiler=Visual Studio
    compiler.version=8.1
[options]
    use_Qt=True
[full_requires]
  Hello2/0.1@lasote/stable:11111
  OpenSSL/2.10@lasote/testing:2222
  HelloInfo1/0.45@myuser/testing:33333
'''

conan_vars1b = '''
[settings]
    arch=x86
    compiler=gcc
    compiler.version=4.3
    compiler.libcxx=libstdc++
[options]
    use_Qt=True
'''

conan_vars1c = '''
[settings]
    os=Linux
    arch=x86
    compiler=gcc
    compiler.version=4.5
    compiler.libcxx=libstdc++11
[options]
    use_Qt=False
[full_requires]
  Hello2/0.1@lasote/stable:11111
  OpenSSL/2.10@lasote/testing:2222
  HelloInfo1/0.45@myuser/testing:33333
[recipe_hash]
  d41d8cd98f00b204e9800998ecf8427e
'''  # The recipe_hash correspond to the faked conanmanifests in export

conan_vars2 = '''
[options]
    use_OpenGL=True
[settings]
    arch=x64
    os=Ubuntu
    version=15.04
'''

conan_vars3 = '''
[options]
    HAVE_TESTS=True
    USE_CONFIG=False
[settings]
    os=Darwin
'''

conan_vars4 = """[settings]
  os=Windows
  arch=x86_64
  compiler=gcc
[options]
  language=1
[full_requires]
  Hello2/0.1@lasote/stable:11111
  OpenSSL/2.10@lasote/testing:2222
  HelloInfo1/0.45@myuser/testing:33333
"""

conan_vars_tool_winx86 = """[settings]
  os_build=Windows
  arch_build=x86
"""

conan_vars_tool_winx64 = """[settings]
  os_build=Windows
  arch_build=x86_64
"""

conan_vars_tool_linx86 = """[settings]
  os_build=Linux
  arch_build=x86
"""

conan_vars_tool_linx64 = """[settings]
  os_build=Linux
  arch_build=x86_64
"""


class SearchTest(unittest.TestCase):

    def setUp(self):
        self.servers = OrderedDict()
        self.servers["local"] = TestServer(server_capabilities=[])
        self.servers["search_able"] = TestServer(server_capabilities=[COMPLEX_SEARCH_CAPABILITY])

        self.client = TestClient(servers=self.servers)

        # No conans created
        self.client.run("search")
        output = self.client.out
        self.assertIn('There are no packages', output)

        # Conans with and without packages created
        root_folder1 = 'Hello/1.4.10/myuser/testing'
        root_folder2 = 'helloTest/1.4.10/myuser/stable'
        root_folder3 = 'Bye/0.14/myuser/testing'
        root_folder4 = 'NodeInfo/1.0.2/myuser/stable'
        root_folder5 = 'MissFile/1.0.2/myuser/stable'
        root_folder11 = 'Hello/1.4.11/myuser/testing'
        root_folder12 = 'Hello/1.4.12/myuser/testing'
        root_folder_tool = 'Tool/1.0.0/myuser/testing'

        self.client.save({"Empty/1.10/fake/test/export/fake.txt": "//",
                          "%s/%s/WindowsPackageSHA/%s" % (root_folder1,
                                                          PACKAGES_FOLDER,
                                                          CONANINFO): conan_vars1,
                          "%s/%s/WindowsPackageSHA/%s" % (root_folder11,
                                                          PACKAGES_FOLDER,
                                                          CONANINFO): conan_vars1,
                          "%s/%s/WindowsPackageSHA/%s" % (root_folder12,
                                                          PACKAGES_FOLDER,
                                                          CONANINFO): conan_vars1,
                          "%s/%s/PlatformIndependantSHA/%s" % (root_folder1,
                                                               PACKAGES_FOLDER,
                                                               CONANINFO): conan_vars1b,
                          "%s/%s/LinuxPackageSHA/%s" % (root_folder1,
                                                        PACKAGES_FOLDER,
                                                        CONANINFO): conan_vars1c,
                          "%s/%s/a44f541cd44w57/%s" % (root_folder2,
                                                       PACKAGES_FOLDER,
                                                       CONANINFO): conan_vars2,
                          "%s/%s/e4f7vdwcv4w55d/%s" % (root_folder3,
                                                       PACKAGES_FOLDER,
                                                       CONANINFO): conan_vars3,
                          "%s/%s/e4f7vdwcv4w55d/%s" % (root_folder4,
                                                       PACKAGES_FOLDER,
                                                       CONANINFO): conan_vars4,
                          "%s/%s/e4f7vdwcv4w55d/%s" % (root_folder5,
                                                       PACKAGES_FOLDER,
                                                       "hello.txt"): "Hello",
                          "%s/%s/winx86/%s" % (root_folder_tool,
                                               PACKAGES_FOLDER,
                                               CONANINFO): conan_vars_tool_winx86,
                          "%s/%s/winx64/%s" % (root_folder_tool,
                                               PACKAGES_FOLDER,
                                               CONANINFO): conan_vars_tool_winx64,
                          "%s/%s/linx86/%s" % (root_folder_tool,
                                               PACKAGES_FOLDER,
                                               CONANINFO): conan_vars_tool_linx86,
                          "%s/%s/linx64/%s" % (root_folder_tool,
                                               PACKAGES_FOLDER,
                                               CONANINFO): conan_vars_tool_linx64},
                         self.client.cache.store)
        # Fake metadata

        def create_metadata(folder, pids):
            metadata = PackageMetadata()
            metadata.recipe.revision = DEFAULT_REVISION_V1
            for pid in pids:
                metadata.packages[pid].revision = DEFAULT_REVISION_V1
            save(os.path.join(self.client.cache.store, folder, "metadata.json"), metadata.dumps())

        create_metadata(root_folder1, ["WindowsPackageSHA", "PlatformIndependantSHA",
                                       "LinuxPackageSHA"])
        create_metadata(root_folder11, ["WindowsPackageSHA"])
        create_metadata(root_folder12, ["WindowsPackageSHA"])
        create_metadata(root_folder2, ["a44f541cd44w57"])
        create_metadata(root_folder3, ["e4f7vdwcv4w55d"])
        create_metadata(root_folder4, ["e4f7vdwcv4w55d"])
        create_metadata(root_folder5, ["e4f7vdwcv4w55d"])
        create_metadata(root_folder_tool, ["winx86", "winx64", "linx86", "linx64"])

        # Fake some manifests to be able to calculate recipe hash
        fake_manifest = FileTreeManifest(1212, {})
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder1, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder2, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder3, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder4, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder5, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder11, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder12, EXPORT_FOLDER))
        fake_manifest.save(os.path.join(self.client.cache.store, root_folder_tool, EXPORT_FOLDER))

    def recipe_search_all_test(self):
        os.rmdir(self.servers["local"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["local"].server_store)
        os.rmdir(self.servers["search_able"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["search_able"].server_store)

        def check():
            for remote in ("local", "search_able"):
                expected = """Remote '{}':
Hello/1.4.10@myuser/testing
Hello/1.4.11@myuser/testing
Hello/1.4.12@myuser/testing
helloTest/1.4.10@myuser/stable""".format(remote)
                self.assertIn(expected, self.client.out)

        self.client.run("search Hello* -r=all")
        check()

        self.client.run("search Hello* -r=all --raw")
        check()

    def recipe_search_test(self):
        self.client.run("search Hello*")
        self.assertEqual("Existing package recipes:\n\n"
                          "Hello/1.4.10@myuser/testing\n"
                          "Hello/1.4.11@myuser/testing\n"
                          "Hello/1.4.12@myuser/testing\n"
                          "helloTest/1.4.10@myuser/stable\n", self.client.out)

        self.client.run("search Hello* --case-sensitive")
        self.assertEqual("Existing package recipes:\n\n"
                          "Hello/1.4.10@myuser/testing\n"
                          "Hello/1.4.11@myuser/testing\n"
                          "Hello/1.4.12@myuser/testing\n", self.client.out)

        self.client.run("search *myuser* --case-sensitive")
        self.assertEqual("Existing package recipes:\n\n"
                          "Bye/0.14@myuser/testing\n"
                          "Hello/1.4.10@myuser/testing\n"
                          "Hello/1.4.11@myuser/testing\n"
                          "Hello/1.4.12@myuser/testing\n"
                          "MissFile/1.0.2@myuser/stable\n"
                          "NodeInfo/1.0.2@myuser/stable\n"
                          "Tool/1.0.0@myuser/testing\n"
                          "helloTest/1.4.10@myuser/stable\n", self.client.out)

        self.client.run("search Hello/*@myuser/testing")
        self.assertIn("Hello/1.4.10@myuser/testing\n"
                      "Hello/1.4.11@myuser/testing\n"
                      "Hello/1.4.12@myuser/testing\n", self.client.out)

    def search_partial_match_test(self):
        self.client.run("search Hello")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n"
                         "Hello/1.4.11@myuser/testing\n"
                         "Hello/1.4.12@myuser/testing\n", self.client.out)

        self.client.run("search hello")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n"
                         "Hello/1.4.11@myuser/testing\n"
                         "Hello/1.4.12@myuser/testing\n", self.client.out)

        self.client.run("search Hello --case-sensitive")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n"
                         "Hello/1.4.11@myuser/testing\n"
                         "Hello/1.4.12@myuser/testing\n", self.client.out)

        self.client.run("search Hel")
        self.assertEqual("There are no packages matching the 'Hel' pattern\n", self.client.out)

        self.client.run("search Hello/")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n"
                         "Hello/1.4.11@myuser/testing\n"
                         "Hello/1.4.12@myuser/testing\n", self.client.out)

        self.client.run("search Hello/1.4.10")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n", self.client.out)

        self.client.run("search Hello/1.4")
        self.assertEqual("There are no packages matching the 'Hello/1.4' pattern\n",
                         self.client.out)

        self.client.run("search Hello/1.4.10@")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n", self.client.out)

        self.client.run("search Hello/1.4.10@myuser")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n", self.client.out)

        self.client.run("search Hello/1.4.10@fen")
        self.assertEqual("There are no packages matching the 'Hello/1.4.10@fen' pattern\n",
                         self.client.out)

        self.client.run("search Hello/1.4.10@myuser/")
        self.assertEqual("Existing package recipes:\n\n"
                         "Hello/1.4.10@myuser/testing\n", self.client.out)

        self.client.run("search Hello/1.4.10@myuser/test", assert_error=True)
        self.assertEqual("ERROR: Recipe not found: 'Hello/1.4.10@myuser/test'\n", self.client.out)

    def search_raw_test(self):
        self.client.run("search Hello* --raw")
        self.assertEqual("Hello/1.4.10@myuser/testing\n"
                         "Hello/1.4.11@myuser/testing\n"
                         "Hello/1.4.12@myuser/testing\n"
                         "helloTest/1.4.10@myuser/stable\n", self.client.out)

    def search_html_table_test(self):
        self.client.run("search Hello/1.4.10@myuser/testing --table=table.html")
        html = load(os.path.join(self.client.current_folder, "table.html"))
        self.assertIn("<h1>Hello/1.4.10@myuser/testing</h1>", html)
        self.assertIn("<td>Linux gcc 4.5 (libstdc++11)</td>", html)
        self.assertIn("<td>Windows Visual Studio 8.1</td>", html)

    def search_html_table_all_test(self):
        os.rmdir(self.servers["local"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["local"].server_store)
        os.rmdir(self.servers["search_able"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["search_able"].server_store)

        self.client.run("search Hello/1.4.10@myuser/testing -r=all --table=table.html")
        html = load(os.path.join(self.client.current_folder, "table.html"))

        self.assertIn("<h1>Hello/1.4.10@myuser/testing</h1>", html)
        self.assertIn("<h2>'local':</h2>", html)
        self.assertIn("<h2>'search_able':</h2>", html)

        self.assertEqual(html.count("<td>Linux gcc 4.5 (libstdc++11)</td>"), 2)
        self.assertEqual(html.count("<td>Windows Visual Studio 8.1</td>"), 2)

    def search_html_table_with_no_reference_test(self):
        self.client.run("search Hello* --table=table.html", assert_error=True)
        self.assertIn("ERROR: '--table' argument can only be used with a reference",
                      self.client.out)

    def package_search_with_invalid_reference_test(self):
        self.client.run("search Hello -q 'a=1'", assert_error=True)
        self.assertIn("-q parameter only allowed with a valid recipe", str(self.client.out))

    def package_search_with_empty_query_test(self):
        self.client.run("search Hello/1.4.10@myuser/testing")
        self.assertIn("WindowsPackageSHA", self.client.out)
        self.assertIn("PlatformIndependantSHA", self.client.out)
        self.assertIn("LinuxPackageSHA", self.client.out)

    def package_search_nonescaped_characters_test(self):
        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.libcxx=libstdc++11"')
        self.assertIn("LinuxPackageSHA", self.client.out)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("WindowsPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.libcxx=libstdc++"')
        self.assertNotIn("LinuxPackageSHA", self.client.out)
        self.assertIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("WindowsPackageSHA", self.client.out)

        # Now search with a remote
        os.rmdir(self.servers["local"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["local"].server_store)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.libcxx=libstdc++11" -r local')
        self.assertIn("Outdated from recipe: False", self.client.out)
        self.assertIn("LinuxPackageSHA", self.client.out)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("WindowsPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.libcxx=libstdc++" -r local')
        self.assertNotIn("LinuxPackageSHA", self.client.out)
        self.assertIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("WindowsPackageSHA", self.client.out)

        # Now search in all remotes
        os.rmdir(self.servers["search_able"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["search_able"].server_store)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.libcxx=libstdc++11" -r all')
        self.assertEqual(str(self.client.out).count("Outdated from recipe: False"), 2)
        self.assertEqual(str(self.client.out).count("LinuxPackageSHA"), 2)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("WindowsPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.libcxx=libstdc++" -r all')
        self.assertNotIn("LinuxPackageSHA", self.client.out)
        self.assertEqual(str(self.client.out).count("PlatformIndependantSHA"), 2)
        self.assertNotIn("WindowsPackageSHA", self.client.out)

    def _assert_pkg_q(self, query, packages_found, remote):

        command = 'search Hello/1.4.10@myuser/testing -q \'%s\'' % query
        if remote:
            command += " -r %s" % remote
        self.client.run(command)

        for pack_name in ["LinuxPackageSHA", "PlatformIndependantSHA", "WindowsPackageSHA"]:
            self.assertEqual(pack_name in self.client.out,
                              pack_name in packages_found, "%s fail" % pack_name)

    def _assert_pkg_query_tool(self, query, packages_found, remote):
        command = 'search Tool/1.0.0@myuser/testing -q \'%s\'' % query
        if remote:
            command += " -r %s" % remote
        self.client.run(command)

        for pack_name in ["winx86", "winx64", "linx86", "linx64"]:
            self.assertEqual(pack_name in self.client.out,
                              pack_name in packages_found, "%s fail" % pack_name)

    def package_search_complex_queries_test(self):

        def test_cases(remote=None):

            if remote:  # Simulate upload to remote
                os.rmdir(self.servers[remote].server_store.store)
                self._copy_to_server(self.client.cache, self.servers[remote].server_store)

            q = ''
            self._assert_pkg_q(q, ["LinuxPackageSHA", "PlatformIndependantSHA",
                                   "WindowsPackageSHA"], remote)
            q = 'compiler="gcc"'
            self._assert_pkg_q(q, ["LinuxPackageSHA", "PlatformIndependantSHA"], remote)

            q = 'compiler='  # No packages found with empty value
            self._assert_pkg_q(q, [], remote)

            q = 'compiler="gcc" OR compiler.libcxx=libstdc++11'
            # Should find Visual because of the OR, visual doesn't care about libcxx
            self._assert_pkg_q(q, ["LinuxPackageSHA", "PlatformIndependantSHA"], remote)

            q = '(compiler="gcc" AND compiler.libcxx=libstdc++11) OR compiler.version=4.5'
            self._assert_pkg_q(q, ["LinuxPackageSHA"], remote)

            q = '(compiler="gcc" AND compiler.libcxx=libstdc++11) OR '\
                '(compiler.version=4.5 OR compiler.version=8.1)'
            self._assert_pkg_q(q, ["LinuxPackageSHA", "WindowsPackageSHA"], remote)

            q = '(compiler="gcc" AND compiler.libcxx=libstdc++) OR '\
                '(compiler.version=4.5 OR compiler.version=8.1)'
            self._assert_pkg_q(q, ["LinuxPackageSHA", "PlatformIndependantSHA",
                                   "WindowsPackageSHA"], remote)

            q = '(compiler="gcc" AND compiler.libcxx=libstdc++) OR '\
                '(compiler.version=4.3 OR compiler.version=8.1)'
            self._assert_pkg_q(q, ["PlatformIndependantSHA", "WindowsPackageSHA"], remote)

            q = '(os="Linux" OR os=Windows)'
            self._assert_pkg_q(q, ["LinuxPackageSHA", "WindowsPackageSHA"], remote)

            q = '(os="Linux" OR os=None)'
            self._assert_pkg_q(q, ["LinuxPackageSHA", "PlatformIndependantSHA"], remote)

            q = '(os=None)'
            self._assert_pkg_q(q, ["PlatformIndependantSHA"], remote)

            q = '(os="Linux" OR os=Windows) AND use_Qt=True'
            self._assert_pkg_q(q, ["WindowsPackageSHA"], remote)

            q = '(os=None OR os=Windows) AND use_Qt=True'
            self._assert_pkg_q(q, ["PlatformIndependantSHA", "WindowsPackageSHA"], remote)

            q = '(os="Linux" OR os=Windows) AND use_Qt=True AND nonexistant_option=3'
            self._assert_pkg_q(q, [], remote)

            q = '(os="Linux" OR os=Windows) AND use_Qt=True OR nonexistant_option=3'
            self._assert_pkg_q(q, ["WindowsPackageSHA", "LinuxPackageSHA"], remote)

            q = 'os_build="Windows"'
            self._assert_pkg_query_tool(q, ["winx86", "winx64"], remote)

            q = 'os_build="Linux"'
            self._assert_pkg_query_tool(q, ["linx86", "linx64"], remote)

            q = 'arch_build="x86"'
            self._assert_pkg_query_tool(q, ["winx86", "linx86"], remote)

            q = 'arch_build="x86_64"'
            self._assert_pkg_query_tool(q, ["winx64", "linx64"], remote)

            q = 'os_build="Windows" AND arch_build="x86_64"'
            self._assert_pkg_query_tool(q, ["winx64"], remote)

            q = 'os_build="Windoooows"'
            self._assert_pkg_query_tool(q, [], remote)

        # test in local
        test_cases()

        # test in remote
        test_cases(remote="local")

        # test in remote with search capabilities
        test_cases(remote="search_able")

    def _copy_to_server(self, cache, server_store):
        subdirs = list_folder_subdirs(basedir=cache.store, level=4)
        refs = [ConanFileReference(*folder.split("/"), revision=DEFAULT_REVISION_V1)
                for folder in subdirs]
        for ref in refs:
            origin_path = cache.package_layout(ref).export()
            dest_path = server_store.export(ref)
            shutil.copytree(origin_path, dest_path)
            server_store.update_last_revision(ref)
            packages = cache.package_layout(ref).packages()
            if not os.path.exists(packages):
                continue
            for package in os.listdir(packages):
                pref = PackageReference(ref, package, DEFAULT_REVISION_V1)
                origin_path = cache.package_layout(ref).package(pref)
                dest_path = server_store.package(pref)
                shutil.copytree(origin_path, dest_path)
                server_store.update_last_package_revision(pref)

    def package_search_all_remotes_test(self):
        os.rmdir(self.servers["local"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["local"].server_store)
        os.rmdir(self.servers["search_able"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["search_able"].server_store)

        self.client.run("search Hello/1.4.10@myuser/testing -r=all")
        self.assertIn("Existing recipe in remote 'local':", self.client.out)
        self.assertIn("Existing recipe in remote 'search_able':", self.client.out)

        self.assertEqual(str(self.client.out).count("WindowsPackageSHA"), 2)
        self.assertEqual(str(self.client.out).count("PlatformIndependantSHA"), 2)
        self.assertEqual(str(self.client.out).count("LinuxPackageSHA"), 2)

    def package_search_with_invalid_query_test(self):
        self.client.run("search Hello/1.4.10@myuser/testing -q 'invalid'", assert_error=True)
        self.assertIn("Invalid package query: invalid", self.client.out)

        self.client.run("search Hello/1.4.10@myuser/testing -q 'os= 3'", assert_error=True)
        self.assertIn("Invalid package query: os= 3", self.client.out)

        self.client.run("search Hello/1.4.10@myuser/testing -q 'os=3 FAKE '", assert_error=True)
        self.assertIn("Invalid package query: os=3 FAKE ", self.client.out)

        self.client.run("search Hello/1.4.10@myuser/testing -q 'os=3 os.compiler=4'",
                        assert_error=True)
        self.assertIn("Invalid package query: os=3 os.compiler=4", self.client.out)

        self.client.run("search Hello/1.4.10@myuser/testing -q 'not os=3 AND os.compiler=4'",
                        assert_error=True)
        self.assertIn("Invalid package query: not os=3 AND os.compiler=4. "
                      "'not' operator is not allowed",
                      self.client.out)

        self.client.run("search Hello/1.4.10@myuser/testing -q 'os=3 AND !os.compiler=4'",
                        assert_error=True)
        self.assertIn("Invalid package query: os=3 AND !os.compiler=4. '!' character is not allowed",
                      self.client.out)

    def package_search_properties_filter_test(self):

        # All packages without filter
        self.client.run("search Hello/1.4.10@myuser/testing -q ''")

        self.assertIn("WindowsPackageSHA", self.client.out)
        self.assertIn("PlatformIndependantSHA", self.client.out)
        self.assertIn("LinuxPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing -q os=Windows')
        self.assertIn("WindowsPackageSHA", self.client.out)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("LinuxPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing -q "os=Windows or os=None"')
        self.assertIn("WindowsPackageSHA", self.client.out)
        self.assertIn("PlatformIndependantSHA", self.client.out)
        self.assertNotIn("LinuxPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing -q "os=Windows or os=Linux"')
        self.assertIn("WindowsPackageSHA", self.client.out)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertIn("LinuxPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "os=Windows AND compiler.version=4.5"')
        self.assertIn("There are no packages for reference 'Hello/1.4.10@myuser/testing' "
                      "matching the query 'os=Windows AND compiler.version=4.5'", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing -q "os=Linux AND compiler.version=4.5"')
        self.assertNotIn("WindowsPackageSHA", self.client.out)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertIn("LinuxPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing -q "compiler.version=1.0"')
        self.assertIn("There are no packages for reference 'Hello/1.4.10@myuser/testing' "
                      "matching the query 'compiler.version=1.0'", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing '
                        '-q "compiler=gcc AND compiler.version=4.5"')
        self.assertNotIn("WindowsPackageSHA", self.client.out)
        self.assertNotIn("PlatformIndependantSHA", self.client.out)
        self.assertIn("LinuxPackageSHA", self.client.out)

        self.client.run('search Hello/1.4.10@myuser/testing -q "arch=x86"')
        # One package will be outdated from recipe and another don't
        self.assertEqual("""Existing packages for recipe Hello/1.4.10@myuser/testing:

    Package_ID: LinuxPackageSHA
        [options]
            use_Qt: False
        [settings]
            arch: x86
            compiler: gcc
            compiler.libcxx: libstdc++11
            compiler.version: 4.5
            os: Linux
        [requires]
            Hello2/0.1@lasote/stable:11111
            HelloInfo1/0.45@myuser/testing:33333
            OpenSSL/2.10@lasote/testing:2222
        Outdated from recipe: False

    Package_ID: PlatformIndependantSHA
        [options]
            use_Qt: True
        [settings]
            arch: x86
            compiler: gcc
            compiler.libcxx: libstdc++
            compiler.version: 4.3
        Outdated from recipe: True

""", self.client.out)

        self.client.run('search helloTest/1.4.10@myuser/stable -q use_OpenGL=False')
        self.assertIn("There are no packages for reference 'helloTest/1.4.10@myuser/stable' "
                      "matching the query 'use_OpenGL=False'", self.client.out)

        self.client.run('search helloTest/1.4.10@myuser/stable -q use_OpenGL=True')
        self.assertIn("Existing packages for recipe helloTest/1.4.10@myuser/stable", self.client.out)

        self.client.run('search helloTest/1.4.10@myuser/stable -q "use_OpenGL=True AND arch=x64"')
        self.assertIn("Existing packages for recipe helloTest/1.4.10@myuser/stable", self.client.out)

        self.client.run('search helloTest/1.4.10@myuser/stable -q "use_OpenGL=True AND arch=x86"')
        self.assertIn("There are no packages for reference 'helloTest/1.4.10@myuser/stable' "
                      "matching the query 'use_OpenGL=True AND arch=x86'", self.client.out)

    def search_with_no_local_test(self):
        client = TestClient()
        client.run("search nonexist/1.0@lasote/stable", assert_error=True)
        self.assertIn("ERROR: Recipe not found: 'nonexist/1.0@lasote/stable'", client.out)

    def search_with_no_registry_test(self):
        # https://github.com/conan-io/conan/issues/2589
        client = TestClient()
        os.remove(client.cache.registry_path)
        client.run("search nonexist/1.0@lasote/stable -r=myremote", assert_error=True)
        self.assertIn("WARN: Remotes registry file missing, creating default one", client.out)
        self.assertIn("ERROR: No remote 'myremote' defined in remotes", client.out)

    def search_json_test(self):
        # Test invalid arguments
        self.client.run("search h* -r all --json search.json --table table.html", assert_error=True)
        self.assertIn("'--table' argument cannot be used together with '--json'", self.client.out)
        json_path = os.path.join(self.client.current_folder, "search.json")
        self.assertFalse(os.path.exists(json_path))

        # Test search packages for unknown reference
        self.client.run("search fake/0.1@danimtb/testing --json search.json", assert_error=True)

        json_path = os.path.join(self.client.current_folder, "search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        self.assertTrue(output["error"])
        self.assertEqual(0, len(output["results"]))

        # Test search recipes local
        self.client.run("search Hello* --json search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        expected_output = {
            'error': False,
            'results': [
                {
                    'remote': None,
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'Hello/1.4.11@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'Hello/1.4.12@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'helloTest/1.4.10@myuser/stable'}
                        }
                    ]
                }
            ]
        }
        self.assertEqual(expected_output, output)

        # Test search recipes all remotes
        os.rmdir(self.servers["local"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["local"].server_store)
        os.rmdir(self.servers["search_able"].server_store.store)
        self._copy_to_server(self.client.cache, self.servers["search_able"].server_store)

        self.client.run("search Hello* -r=all --json search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        expected_output = {
            'error': False,
            'results': [
                {
                    'remote': 'local',
                    'items': [
                        {
                             'recipe': {
                                 'id': 'Hello/1.4.10@myuser/testing'}
                        },
                        {
                             'recipe': {
                                 'id': 'Hello/1.4.11@myuser/testing'}
                        },
                        {
                             'recipe': {
                                 'id': 'Hello/1.4.12@myuser/testing'}
                        },
                        {
                             'recipe': {
                                 'id': 'helloTest/1.4.10@myuser/stable'}
                        }
                    ]
                },
                {
                    'remote': 'search_able',
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'Hello/1.4.11@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'Hello/1.4.12@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'helloTest/1.4.10@myuser/stable'}
                        }
                    ]
                }
            ]
        }
        self.assertEqual(expected_output, output)

        # Test search recipe remote
        self.client.run("search Hello* -r=local --json search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        expected_output = {
            'error': False,
            'results': [
                {
                    'remote': 'local',
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'Hello/1.4.11@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'Hello/1.4.12@myuser/testing'}
                        },
                        {
                            'recipe': {
                                'id': 'helloTest/1.4.10@myuser/stable'}
                        }
                    ]
                }
            ]
        }
        self.assertEqual(expected_output, output)

        # Test search packages local
        self.client.run("search Hello/1.4.10@myuser/testing --json search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        expected_output = {
            'error': False,
            'results': [
                {
                    'remote': None,
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'},
                            'packages': [
                                {
                                    'id': 'LinuxPackageSHA',
                                    'options': {
                                        'use_Qt': 'False'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++11',
                                        'compiler.version': '4.5',
                                        'os': 'Linux'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': False
                                },
                                {
                                    'id': 'PlatformIndependantSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++',
                                        'compiler.version': '4.3'},
                                    'requires': [],
                                    'outdated': True
                                },
                                {
                                    'id': 'WindowsPackageSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x64',
                                        'compiler': 'Visual Studio',
                                        'compiler.version': '8.1',
                                        'os': 'Windows'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': True
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        self.assertEqual(expected_output, output)

        # Test search packages remote
        self.client.run("search Hello/1.4.10@myuser/testing -r search_able --json search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        expected_output = {
            'error': False,
            'results': [
                {
                    'remote': 'search_able',
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'},
                            'packages': [
                                {
                                    'id': 'LinuxPackageSHA',
                                    'options': {
                                        'use_Qt': 'False'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++11',
                                        'compiler.version': '4.5',
                                        'os': 'Linux'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': False
                                },
                                {
                                    'id': 'PlatformIndependantSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++',
                                        'compiler.version': '4.3'},
                                    'requires': [],
                                    'outdated': True
                                },
                                {
                                    'id': 'WindowsPackageSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x64',
                                        'compiler': 'Visual Studio',
                                        'compiler.version': '8.1',
                                        'os': 'Windows'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': True
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        self.assertEqual(expected_output, output)

        # Test search packages remote ALL
        self.client.run("search Hello/1.4.10@myuser/testing -r all --json search.json")
        self.assertTrue(os.path.exists(json_path))
        json_content = load(json_path)
        output = json.loads(json_content)
        expected_output = {
            'error': False,
            'results': [
                {
                    'remote': 'local',
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'},
                            'packages': [
                                {
                                    'id': 'LinuxPackageSHA',
                                    'options': {
                                        'use_Qt': 'False'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++11',
                                        'compiler.version': '4.5',
                                        'os': 'Linux'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': False
                                },
                                {
                                    'id': 'PlatformIndependantSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++',
                                        'compiler.version': '4.3'},
                                    'requires': [],
                                    'outdated': True
                                },
                                {
                                    'id': 'WindowsPackageSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x64',
                                        'compiler': 'Visual Studio',
                                        'compiler.version': '8.1',
                                        'os': 'Windows'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': True
                                }
                            ]
                        }
                    ]
                },
                {
                    'remote': 'search_able',
                    'items': [
                        {
                            'recipe': {
                                'id': 'Hello/1.4.10@myuser/testing'},
                            'packages': [
                                {
                                    'id': 'LinuxPackageSHA',
                                    'options': {
                                        'use_Qt': 'False'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++11',
                                        'compiler.version': '4.5',
                                        'os': 'Linux'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': False
                                },
                                {
                                    'id': 'PlatformIndependantSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x86',
                                        'compiler': 'gcc',
                                        'compiler.libcxx': 'libstdc++',
                                        'compiler.version': '4.3'},
                                    'requires': [],
                                    'outdated': True
                                },
                                {
                                    'id': 'WindowsPackageSHA',
                                    'options': {
                                        'use_Qt': 'True'},
                                    'settings': {
                                        'arch': 'x64',
                                        'compiler': 'Visual Studio',
                                        'compiler.version': '8.1',
                                        'os': 'Windows'},
                                    'requires': [
                                        'Hello2/0.1@lasote/stable:11111',
                                        'HelloInfo1/0.45@myuser/testing:33333',
                                        'OpenSSL/2.10@lasote/testing:2222'],
                                    'outdated': True
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        self.assertEqual(expected_output, output)

    def search_packages_with_reference_not_exported_test(self):
        self.client.run("search my_pkg/1.0@conan/stable", assert_error=True)
        self.assertIn("ERROR: Recipe not found: 'my_pkg/1.0@conan/stable'", self.client.out)

    def initial_search_without_registry_test(self):
        client = TestClient()
        os.remove(client.cache.registry_path)
        client.run("search my_pkg")
        self.assertIn("WARN: Remotes registry file missing, creating default one", client.out)
        self.assertIn("There are no packages matching the 'my_pkg' pattern", client.out)


@unittest.skipIf(get_env("TESTING_REVISIONS_ENABLED", False), "No sense with revs")
class SearchOutdatedTest(unittest.TestCase):
    def search_outdated_test(self):
        test_server = TestServer(users={"lasote": "password"})  # exported users and passwords
        servers = {"default": test_server}
        client = TestClient(servers=servers, users={"default": [("lasote", "password")]})
        conanfile = """from conans import ConanFile
class Test(ConanFile):
    name = "Test"
    version = "0.1"
    settings = "os"
    """
        client.save({"conanfile.py": conanfile})
        client.run("export . lasote/testing")
        client.run("install Test/0.1@lasote/testing --build -s os=Windows")
        client.save({"conanfile.py": "# comment\n%s" % conanfile})
        client.run("export . lasote/testing")
        client.run("install Test/0.1@lasote/testing --build -s os=Linux")
        client.run("upload * --all --confirm")
        for remote in ("", "-r=default"):
            client.run("search Test/0.1@lasote/testing %s" % remote)
            self.assertIn("os: Windows", client.user_io.out)
            self.assertIn("os: Linux", client.user_io.out)
            client.run("search Test/0.1@lasote/testing  %s --outdated" % remote)
            self.assertIn("os: Windows", client.user_io.out)
            self.assertNotIn("os: Linux", client.user_io.out)

    def test_exception_client_without_revs(self):
        client = TestClient()
        client.run("search whatever --revisions", assert_error=True)
        self.assertIn("ERROR: With --revision, specify a reference", client.out)

        client.run("search lib/0.1@user/testing --revisions", assert_error=True)
        self.assertIn("ERROR: The client doesn't have the revisions feature enabled", client.out)


@unittest.skipUnless(get_env("TESTING_REVISIONS_ENABLED", False),
                     "set TESTING_REVISIONS_ENABLED=1")
class SearchRevisionsTest(unittest.TestCase):

    def search_recipe_revisions_test(self):
        test_server = TestServer(users={"user": "password"})  # exported users and passwords
        servers = {"default": test_server}
        client = TestClient(servers=servers, users={"default": [("user", "password")]})

        conanfile = """
from conans import ConanFile
class Test(ConanFile):
    pass
"""
        the_time = time.time()
        time_str = iso8601_to_str(from_timestamp_to_iso8601(the_time))

        time.sleep(1)

        client.save({"conanfile.py": conanfile})
        client.run("export . lib/1.0@user/testing")

        # If the recipe doesn't have associated remote, there is no time
        client.run("search lib/1.0@user/testing --revisions")
        self.assertIn("bd761686d5c57b31f4cd85fd0329751f (No time)", client.out)

        with patch.object(RevisionList, '_now', return_value=the_time):
            client.run("upload lib/1.0@user/testing -c")

        # Now the revision exists in the server, so it is printed
        client.run("search lib/1.0@user/testing --revisions")
        self.assertIn("bd761686d5c57b31f4cd85fd0329751f ({})".format(time_str), client.out)

        # Create new revision and upload
        client.save({"conanfile.py": conanfile + "# force new rev"})
        client.run("export . lib/1.0@user/testing")

        client.run("search lib/1.0@user/testing --revisions")
        self.assertNotIn("bd761686d5c57b31f4cd85fd0329751f", client.out)
        self.assertIn("a94417fca6b55779c3b158f2ff50c40a", client.out)

        # List remote
        with patch.object(RevisionList, '_now', return_value=the_time):
            client.run("upload lib/1.0@user/testing -c")
        client.run("remove -f lib*")
        client.run("install lib/1.0@user/testing --build")  # To update the local time

        client.run("search lib/1.0@user/testing -r default --revisions")

        self.assertIn("bd761686d5c57b31f4cd85fd0329751f ({})".format(time_str), client.out)
        self.assertIn("a94417fca6b55779c3b158f2ff50c40a ({})".format(time_str), client.out)
        self.assertNotIn("(No time)", client.out)

        json_path = os.path.join(client.current_folder, "search.json")

        # JSON output remote
        client.run('search lib/1.0@user/testing -r default '
                   '--revisions --json "{}"'.format(json_path))
        j = json.loads(load(json_path))
        self.assertEqual(j[0]["revision"], "a94417fca6b55779c3b158f2ff50c40a")
        self.assertIsNotNone(j[0]["time"])
        self.assertEqual(j[1]["revision"], "bd761686d5c57b31f4cd85fd0329751f")
        self.assertIsNotNone(j[1]["time"])
        self.assertEqual(len(j), 2)

        # JSON output local
        client.run('search lib/1.0@user/testing --revisions --json "{}"'.format(json_path))
        j = json.loads(load(json_path))
        self.assertEqual(j[0]["revision"], "a94417fca6b55779c3b158f2ff50c40a")
        self.assertIsNotNone(j[0]["time"])
        self.assertEqual(len(j), 1)

    def search_package_revisions_test(self):
        test_server = TestServer(users={"user": "password"})  # exported users and passwords
        servers = {"default": test_server}
        client = TestClient(servers=servers, users={"default": [("user", "password")]})

        conanfile = """
from conans import ConanFile
class Test(ConanFile):
    pass
"""
        the_time = time.time()
        time_str = iso8601_to_str(from_timestamp_to_iso8601(the_time))

        client.save({"conanfile.py": conanfile})
        client.run("create . lib/1.0@user/testing")
        with patch.object(RevisionList, '_now', return_value=the_time):
            client.run("upload lib/1.0@user/testing -c --all")  # For later remote test
        first_rrev = "bd761686d5c57b31f4cd85fd0329751f"
        first_prev = "e928490f2e24da2ab391f0b289dd73c1"
        full_ref = "lib/1.0@user/testing#{rrev}:%s" % NO_SETTINGS_PACKAGE_ID

        # LOCAL CACHE CHECKS
        client.run("search %s --revisions" % full_ref.format(rrev=first_rrev))

        # The time is checked from the remote, so it is present
        self.assertIn("%s (%s)" % (first_prev, time_str), client.out)

        # If we update, (no updates available) there also time
        client.run("install lib/1.0@user/testing --update")
        client.run("search %s --revisions" % full_ref.format(rrev=first_rrev))
        self.assertIn("%s (%s)" % (first_prev, time_str),  client.out)

        client.run("remove lib/1.0@user/testing -f")
        client.run("install lib/1.0@user/testing")
        # Now installed the package the time is ok
        client.run("search %s --revisions" % full_ref.format(rrev=first_rrev))
        self.assertIn("%s (%s)" % (first_prev, time_str), client.out)

        # Create new revision and upload
        client.save({"conanfile.py": conanfile + "# force new rev"})
        client.run("create . lib/1.0@user/testing")

        with patch.object(RevisionList, '_now', return_value=the_time):
            client.run("upload lib/1.0@user/testing -c --all")  # For later remote test
        client.run("search lib/1.0@user/testing --revisions")
        self.assertIn("a94417fca6b55779c3b158f2ff50c40a", client.out)

        second_rrev = "a94417fca6b55779c3b158f2ff50c40a"
        second_prev = "b520ef8bf841bad7639cea8d3c7d7fa1"
        client.run("search %s --revisions" % full_ref.format(rrev=second_rrev))

        # REMOTE CHECKS
        client.run("search %s -r default --revisions" % full_ref.format(rrev=first_rrev))

        self.assertIn("{} ({})".format(first_prev, time_str), client.out)
        self.assertNotIn(second_prev, client.out)
        self.assertNotIn("(No time)", client.out)

        client.run("search %s -r default --revisions" % full_ref.format(rrev=second_rrev))
        self.assertNotIn(first_prev, client.out)
        self.assertIn(second_prev, client.out)
        self.assertNotIn("(No time)", client.out)

        json_path = os.path.join(client.current_folder, "search.json")

        # JSON output remote
        client.run("search %s -r default --revisions "
                   "--json \"%s\"" % (full_ref.format(rrev=first_rrev), json_path))
        j = json.loads(load(json_path))
        self.assertEqual(j[0]["revision"], first_prev)
        self.assertIsNotNone(j[0]["time"])
        self.assertEqual(len(j), 1)

    def search_not_found_test(self):
        # Search not found for both package and recipe
        test_server = TestServer(users={"conan": "password"})  # exported users and passwords
        servers = {"default": test_server}
        client = TestClient(servers=servers, users={"default": [("conan", "password")]})
        client.run("search missing/1.0@conan/stable --revisions", assert_error=True)
        self.assertIn("ERROR: Recipe not found: 'missing/1.0@conan/stable'", client.out)

        # Search for package revisions for a non existing recipe
        client.run("search missing/1.0@conan/stable#revision:234234234234234234 --revisions",
                   assert_error=True)
        self.assertIn("ERROR: Recipe not found: 'missing/1.0@conan/stable#revision'", client.out)

        # Create a package
        conanfile = """
from conans import ConanFile
class Test(ConanFile):
    pass
"""
        client.save({"conanfile.py": conanfile})
        client.run("create . lib/1.0@conan/stable")
        # Search the wrong revision
        client.run("search lib/1.0@conan/stable#revision:234234234234234234 --revisions",
                   assert_error=True)
        self.assertIn("ERROR: Binary package not found: "
                      "'lib/1.0@conan/stable#revision:234234234234234234'", client.out)
        # Search the right revision but wrong package
        client.run("search lib/1.0@conan/stable#bd761686d5c57b31f4cd85fd0329751f:"
                   "234234234234234234 --revisions", assert_error=True)
        self.assertIn("ERROR: Binary package not found: "
                      "'lib/1.0@conan/stable#bd761686d5c57b31f4cd85fd0329751f:"
                      "234234234234234234'", client.out)

        # IN REMOTE

        # Search not found in remote
        client.run("search missing/1.0@conan/stable --revisions -r default", assert_error=True)
        self.assertIn("ERROR: Recipe not found: 'missing/1.0@conan/stable'", client.out)

        # Search for package revisions for a non existing recipe in remote
        client.run("search missing/1.0@conan/stable#revision:234234234234234234 --revisions "
                   "-r default", assert_error=True)
        self.assertIn("ERROR: Recipe not found: 'missing/1.0@conan/stable#revision'", client.out)

        # Search for a wrong revision in the remote
        client.run("upload lib/1.0@conan/stable -c --all")
        client.run("search lib/1.0@conan/stable#revision:234234234234234234 --revisions "
                   "-r default", assert_error=True)
        self.assertIn("ERROR: Binary package not found: "
                      "'lib/1.0@conan/stable#revision:234234234234234234'", client.out)

        # Search the right revision but wrong package
        client.run("search lib/1.0@conan/stable#bd761686d5c57b31f4cd85fd0329751f:"
                   "234234234234234234 --revisions -r default", assert_error=True)
        self.assertIn("ERROR: Binary package not found: "
                      "'lib/1.0@conan/stable#bd761686d5c57b31f4cd85fd0329751f:"
                      "234234234234234234'", client.out)

    def search_revision_fail_if_v1_server_test(self):
        # V1 server
        test_server = TestServer(users={"conan": "password"}, server_capabilities=[])
        servers = {"default": test_server}
        client = TestClient(servers=servers, users={"default": [("conan", "password")]})
        client.run("search missing/1.0@conan/stable --revisions -r default", assert_error=True)
        self.assertIn("ERROR: The remote doesn't support revisions", client.out)

    def test_invalid_references_test(self):
        client = TestClient()
        # Local errors
        client.run("search missing/1.0@conan/stable#revision --revisions", assert_error=True)
        self.assertIn("Cannot list the revisions of a specific recipe revision", client.out)

        client.run("search missing/1.0@conan/stable:pid#revision --revisions", assert_error=True)
        self.assertIn("Specify a recipe reference with revision", client.out)

        client.run("search missing/1.0@conan/stable#revision:pid#revision --revisions",
                   assert_error=True)
        self.assertIn("Cannot list the revisions of a specific package revision", client.out)

        # Remote errors
        client.run("search missing/1.0@conan/stable#revision --revisions -r fake",
                   assert_error=True)
        self.assertIn("Cannot list the revisions of a specific recipe revision", client.out)

        client.run("search missing/1.0@conan/stable:pid#revision --revisions -r fake",
                   assert_error=True)
        self.assertIn("Specify a recipe reference with revision", client.out)

        client.run("search missing/1.0@conan/stable#revision:pid#revision --revisions -r fake",
                   assert_error=True)
        self.assertIn("Cannot list the revisions of a specific package revision", client.out)

    def test_invalid_command_call(self):
        client = TestClient()
        client.run("search --revisions", assert_error=True)
        self.assertIn("With --revision, specify a reference", client.out)
        self.assertIn("or a package reference with recipe revision", client.out)


class SearchRemoteAllTestCase(unittest.TestCase):
    def setUp(self):
        """ Create a remote called 'all' with some recipe in it """
        self.remote_name = 'all'
        servers = {self.remote_name: TestServer(users={"user": "passwd"})}
        self.client = TestClient(servers=servers, users={self.remote_name: [("user", "passwd")], })

        conanfile = textwrap.dedent("""
            from conans import ConanFile
            class MyLib(ConanFile):
                pass
            """)

        self.reference = "name/version@user/channel"
        self.client.save({'conanfile.py': conanfile})
        self.client.run("export . {}".format(self.reference))
        self.client.run("upload --force -r {} {}".format(self.remote_name, self.reference))

    def test_search_by_name(self):
        self.client.run("remote list")
        self.assertIn("all: http://fake", self.client.out)
        self.client.run("search -r {} {}".format(self.remote_name, self.reference))
        self.assertIn("Existing recipe in remote 'all':", self.client.out)  # Searching in 'all'
