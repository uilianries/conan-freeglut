import os
import unittest
from collections import OrderedDict

from conans.model.ref import ConanFileReference
from conans.test.utils.tools import TestClient, TestServer
from conans.util.files import load


class DownloadTest(unittest.TestCase):

    def download_recipe_test(self):
        server = TestServer()
        servers = {"default": server}
        client = TestClient(servers=servers, users={"default": [("lasote", "mypass")]})

        # Test argument --package and --recipe cannot be together
        client.run("download eigen/3.3.4@conan/stable --recipe --package fake_id",
                   assert_error=True)

        self.assertIn("ERROR: recipe parameter cannot be used together with package", client.out)

        # Test download of the recipe only
        conanfile = """from conans import ConanFile
class Pkg(ConanFile):
    name = "pkg"
    version = "0.1"
    exports_sources = "*"
"""
        client.save({"conanfile.py": conanfile,
                     "file.h": "myfile.h"})
        client.run("create . lasote/stable")
        ref = ConanFileReference.loads("pkg/0.1@lasote/stable")
        self.assertTrue(os.path.exists(client.cache.package_layout(ref).conanfile()))
        conan = client.cache.package_layout(ref).base_folder()
        self.assertTrue(os.path.exists(os.path.join(conan, "package")))
        client.run("upload pkg/0.1@lasote/stable --all")
        client.run("remove pkg/0.1@lasote/stable -f")
        self.assertFalse(os.path.exists(client.cache.package_layout(ref).export()))
        client.run("download pkg/0.1@lasote/stable --recipe")

        self.assertIn("Downloading conanfile.py", client.out)
        self.assertIn("Downloading conan_sources.tgz", client.out)
        self.assertNotIn("Downloading conan_package.tgz", client.out)
        export = client.cache.package_layout(ref).export()
        self.assertTrue(os.path.exists(os.path.join(export, "conanfile.py")))
        self.assertEqual(conanfile, load(os.path.join(export, "conanfile.py")))
        source = client.cache.package_layout(ref).export_sources()
        self.assertTrue(os.path.exists(os.path.join(source, "file.h")))
        conan = client.cache.package_layout(ref).base_folder()
        self.assertFalse(os.path.exists(os.path.join(conan, "package")))

    def download_with_sources_test(self):
        server = TestServer()
        servers = OrderedDict()
        servers["default"] = server
        servers["other"] = TestServer()

        client = TestClient(servers=servers, users={"default": [("lasote", "mypass")],
                                                    "other": [("lasote", "mypass")]})
        conanfile = """from conans import ConanFile
class Pkg(ConanFile):
    name = "pkg"
    version = "0.1"
    exports_sources = "*"
"""
        client.save({"conanfile.py": conanfile,
                     "file.h": "myfile.h",
                     "otherfile.cpp": "C++code"})
        client.run("export . lasote/stable")

        ref = ConanFileReference.loads("pkg/0.1@lasote/stable")
        self.assertTrue(os.path.exists(client.cache.package_layout(ref).conanfile()))

        client.run("upload pkg/0.1@lasote/stable")
        client.run("remove pkg/0.1@lasote/stable -f")
        self.assertFalse(os.path.exists(client.cache.package_layout(ref).export()))

        client.run("download pkg/0.1@lasote/stable")
        self.assertIn("Downloading conan_sources.tgz", client.out)
        source = client.cache.package_layout(ref).export_sources()
        self.assertEqual("myfile.h", load(os.path.join(source, "file.h")))
        self.assertEqual("C++code", load(os.path.join(source, "otherfile.cpp")))

    def download_reference_without_packages_test(self):
        server = TestServer()
        servers = {"default": server}

        client = TestClient(servers=servers, users={"default": [("lasote", "mypass")]})
        conanfile = """from conans import ConanFile
class Pkg(ConanFile):
    name = "pkg"
    version = "0.1"
"""
        client.save({"conanfile.py": conanfile})
        client.run("export . lasote/stable")

        ref = ConanFileReference.loads("pkg/0.1@lasote/stable")
        self.assertTrue(os.path.exists(client.cache.package_layout(ref).conanfile()))

        client.run("upload pkg/0.1@lasote/stable")
        client.run("remove pkg/0.1@lasote/stable -f")
        self.assertFalse(os.path.exists(client.cache.package_layout(ref).export()))

        client.run("download pkg/0.1@lasote/stable")
        # Check 'No remote binary packages found' warning
        self.assertTrue("WARN: No remote binary packages found in remote", client.out)
        # Check at least conanfile.py is downloaded
        self.assertTrue(os.path.exists(client.cache.package_layout(ref).conanfile()))

    def download_reference_with_packages_test(self):
        server = TestServer()
        servers = {"default": server}

        client = TestClient(servers=servers, users={"default": [("lasote", "mypass")]})
        conanfile = """from conans import ConanFile
class Pkg(ConanFile):
    name = "pkg"
    version = "0.1"
    settings = "os"
"""

        client.save({"conanfile.py": conanfile})
        client.run("create . lasote/stable")

        ref = ConanFileReference.loads("pkg/0.1@lasote/stable")
        package_layout = client.cache.package_layout(ref)
        self.assertTrue(os.path.exists(package_layout.conanfile()))

        package_folder = os.path.join(package_layout.packages(),
                                      os.listdir(package_layout.packages())[0])

        client.run("upload pkg/0.1@lasote/stable --all")
        client.run("remove pkg/0.1@lasote/stable -f")
        self.assertFalse(os.path.exists(package_layout.export()))

        client.run("download pkg/0.1@lasote/stable")

        # Check not 'No remote binary packages found' warning
        self.assertNotIn("WARN: No remote binary packages found in remote", client.out)
        # Check at conanfile.py is downloaded
        self.assertTrue(os.path.exists(package_layout.conanfile()))
        # Check package folder created
        self.assertTrue(os.path.exists(package_folder))

    def test_download_wrong_id(self):
        client = TestClient(servers={"default": TestServer()},
                            users={"default": [("lasote", "mypass")]})
        conanfile = """from conans import ConanFile
class Pkg(ConanFile):
    pass
"""
        client.save({"conanfile.py": conanfile})
        client.run("export . pkg/0.1@lasote/stable")
        client.run("upload pkg/0.1@lasote/stable")
        client.run("remove pkg/0.1@lasote/stable -f")

        client.run("download pkg/0.1@lasote/stable -p=wrong", assert_error=True)
        self.assertIn("ERROR: Binary package not found: 'pkg/0.1@lasote/stable:wrong'",
                      client.out)

    def test_download_pattern(self):
        client = TestClient()
        client.run("download pkg/*@user/channel", assert_error=True)
        self.assertIn("Provide a valid full reference without wildcards", client.out)
