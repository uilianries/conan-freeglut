import os
import sys
import textwrap
import unittest
from collections import OrderedDict

import six
from mock import Mock
from mock.mock import call
from parameterized import parameterized

from conans.client.graph.python_requires import ConanPythonRequire
from conans.client.loader import ConanFileLoader, ConanFileTextLoader,\
    _parse_conanfile
from conans.client.tools.files import chdir
from conans.errors import ConanException
from conans.model.options import OptionsValues
from conans.model.profile import Profile
from conans.model.requires import Requirements
from conans.model.settings import Settings
from conans.test.utils.test_files import temp_folder
from conans.test.utils.tools import test_processed_profile,\
    TestBufferConanOutput
from conans.util.files import save


class ConanLoaderTest(unittest.TestCase):

    def inherit_short_paths_test(self):
        loader = ConanFileLoader(None, TestBufferConanOutput(), ConanPythonRequire(None, None))
        tmp_dir = temp_folder()
        conanfile_path = os.path.join(tmp_dir, "conanfile.py")
        conanfile = """from base_recipe import BasePackage
class Pkg(BasePackage):
    pass
"""
        base_recipe = """from conans import ConanFile
class BasePackage(ConanFile):
    short_paths = True
"""
        save(conanfile_path, conanfile)
        save(os.path.join(tmp_dir, "base_recipe.py"), base_recipe)
        conan_file = loader.load_class(conanfile_path)
        self.assertEqual(conan_file.short_paths, True)

        result = loader.load_consumer(conanfile_path,
                                      processed_profile=test_processed_profile())
        self.assertEqual(result.short_paths, True)

    def requires_init_test(self):
        loader = ConanFileLoader(None, TestBufferConanOutput(), ConanPythonRequire(None, None))
        tmp_dir = temp_folder()
        conanfile_path = os.path.join(tmp_dir, "conanfile.py")
        conanfile = """from conans import ConanFile
class MyTest(ConanFile):
    requires = {}
    def requirements(self):
        self.requires("MyPkg/0.1@user/channel")
"""
        for requires in ("''", "[]", "()", "None"):
            save(conanfile_path, conanfile.format(requires))
            result = loader.load_consumer(conanfile_path,
                                          processed_profile=test_processed_profile())
            result.requirements()
            self.assertEqual("MyPkg/0.1@user/channel", str(result.requires))

    def conanfile_txt_errors_test(self):
        # Valid content
        file_content = '''[requires}
OpenCV/2.4.10@phil/stable # My requirement for CV
'''
        with six.assertRaisesRegex(self, ConanException, "Bad syntax"):
            ConanFileTextLoader(file_content)

        file_content = '{hello}'
        with six.assertRaisesRegex(self, ConanException, "Unexpected line"):
            ConanFileTextLoader(file_content)

        file_content = '[imports]\nhello'
        with six.assertRaisesRegex(self, ConanException, "Invalid imports line: hello"):
            ConanFileTextLoader(file_content).imports_method(None)

        file_content = '[imports]\nbin, * -> bin @ kk=3 '
        with six.assertRaisesRegex(self, ConanException, "Unknown argument kk"):
            ConanFileTextLoader(file_content).imports_method(None)

    def plain_text_parser_test(self):
        # Valid content
        file_content = '''[requires]
OpenCV/2.4.10@phil/stable # My requirement for CV
OpenCV2/2.4.10@phil/stable #
OpenCV3/2.4.10@phil/stable
[generators]
one # My generator for this
two
[options]
OpenCV:use_python=True # Some option
OpenCV:other_option=False
OpenCV2:use_python2=1
OpenCV2:other_option=Cosa #
'''
        parser = ConanFileTextLoader(file_content)
        exp = ['OpenCV/2.4.10@phil/stable',
               'OpenCV2/2.4.10@phil/stable',
               'OpenCV3/2.4.10@phil/stable']
        self.assertEqual(parser.requirements, exp)

    def load_conan_txt_test(self):
        file_content = '''[requires]
OpenCV/2.4.10@phil/stable
OpenCV2/2.4.10@phil/stable
[build_requires]
MyPkg/1.0.0@phil/stable
[generators]
one
two
[imports]
OpenCV/bin, * -> ./bin # I need this binaries
OpenCV/lib, * -> ./lib
[options]
OpenCV:use_python=True
OpenCV:other_option=False
OpenCV2:use_python2=1
OpenCV2:other_option=Cosa
'''
        tmp_dir = temp_folder()
        file_path = os.path.join(tmp_dir, "file.txt")
        save(file_path, file_content)
        loader = ConanFileLoader(None, TestBufferConanOutput(), None)
        ret = loader.load_conanfile_txt(file_path, test_processed_profile())
        options1 = OptionsValues.loads("""OpenCV:use_python=True
OpenCV:other_option=False
OpenCV2:use_python2=1
OpenCV2:other_option=Cosa""")
        requirements = Requirements()
        requirements.add("OpenCV/2.4.10@phil/stable")
        requirements.add("OpenCV2/2.4.10@phil/stable")
        build_requirements = []
        build_requirements.append("MyPkg/1.0.0@phil/stable")

        self.assertEqual(ret.requires, requirements)
        self.assertEqual(ret.build_requires, build_requirements)
        self.assertEqual(ret.generators, ["one", "two"])
        self.assertEqual(ret.options.values.dumps(), options1.dumps())

        ret.copy = Mock()
        ret.imports()

        self.assertTrue(ret.copy.call_args_list, [('*', './bin', 'OpenCV/bin'),
                                                  ('*', './lib', 'OpenCV/lib')])

        # Now something that fails
        file_content = '''[requires]
OpenCV/2.4.104phil/stable
'''
        tmp_dir = temp_folder()
        file_path = os.path.join(tmp_dir, "file.txt")
        save(file_path, file_content)
        loader = ConanFileLoader(None, TestBufferConanOutput(), None)
        with six.assertRaisesRegex(self, ConanException, "Wrong package recipe reference(.*)"):
            loader.load_conanfile_txt(file_path, test_processed_profile())

        file_content = '''[requires]
OpenCV/2.4.10@phil/stable111111111111111111111111111111111111111111111111111111111111111
[imports]
OpenCV/bin/* - ./bin
'''
        tmp_dir = temp_folder()
        file_path = os.path.join(tmp_dir, "file.txt")
        save(file_path, file_content)
        loader = ConanFileLoader(None, TestBufferConanOutput(), None)
        with six.assertRaisesRegex(self, ConanException, "is too long. Valid names must contain"):
            loader.load_conanfile_txt(file_path, test_processed_profile())

    def load_imports_arguments_test(self):
        file_content = '''
[imports]
OpenCV/bin, * -> ./bin # I need this binaries
OpenCV/lib, * -> ./lib @ root_package=Pkg
OpenCV/data, * -> ./data @ root_package=Pkg, folder=True # Irrelevant
docs, * -> ./docs @ root_package=Pkg, folder=True, ignore_case=True, excludes="a b c" # Other
licenses, * -> ./licenses @ root_package=Pkg, folder=True, ignore_case=True, excludes="a b c", keep_path=False # Other
'''
        tmp_dir = temp_folder()
        file_path = os.path.join(tmp_dir, "file.txt")
        save(file_path, file_content)
        loader = ConanFileLoader(None, TestBufferConanOutput(), None)
        ret = loader.load_conanfile_txt(file_path, test_processed_profile())

        ret.copy = Mock()
        ret.imports()
        expected = [call(u'*', u'./bin', u'OpenCV/bin', None, False, False, None, True),
                    call(u'*', u'./lib', u'OpenCV/lib', u'Pkg', False, False, None, True),
                    call(u'*', u'./data', u'OpenCV/data', u'Pkg', True, False, None, True),
                    call(u'*', u'./docs', u'docs', u'Pkg', True, True, [u'"a', u'b', u'c"'], True),
                    call(u'*', u'./licenses', u'licenses', u'Pkg', True, True, [u'"a', u'b', u'c"'],
                         False)]
        self.assertEqual(ret.copy.call_args_list, expected)

    def test_package_settings(self):
        # CREATE A CONANFILE TO LOAD
        tmp_dir = temp_folder()
        conanfile_path = os.path.join(tmp_dir, "conanfile.py")
        conanfile = """from conans import ConanFile
class MyTest(ConanFile):
    requires = {}
    name = "MyPackage"
    version = "1.0"
    settings = "os"
"""
        save(conanfile_path, conanfile)

        # Apply windows for MyPackage
        profile = Profile()
        profile.processed_settings = Settings({"os": ["Windows", "Linux"]})
        profile.package_settings = {"MyPackage": OrderedDict([("os", "Windows")])}
        loader = ConanFileLoader(None, TestBufferConanOutput(), ConanPythonRequire(None, None))

        recipe = loader.load_consumer(conanfile_path,
                                      test_processed_profile(profile))
        self.assertEqual(recipe.settings.os, "Windows")

        # Apply Linux for MyPackage
        profile.package_settings = {"MyPackage": OrderedDict([("os", "Linux")])}
        recipe = loader.load_consumer(conanfile_path,
                                      test_processed_profile(profile))
        self.assertEqual(recipe.settings.os, "Linux")

        # If the package name is different from the conanfile one, it wont apply
        profile.package_settings = {"OtherPACKAGE": OrderedDict([("os", "Linux")])}
        recipe = loader.load_consumer(conanfile_path,
                                      test_processed_profile(profile))
        self.assertIsNone(recipe.settings.os.value)


class ImportModuleLoaderTest(unittest.TestCase):
    @staticmethod
    def _create_and_load(myfunc, value, subdir_name, add_subdir_init):
        subdir_content = textwrap.dedent("""
            def get_value():
                return {value}
            def {myfunc}():
                return "{myfunc}"
        """)

        side_content = textwrap.dedent("""
            def get_side_value():
                return {value}
            def side_{myfunc}():
                return "{myfunc}"
        """)

        conanfile = textwrap.dedent("""
            import pickle
            from {subdir}.api import get_value, {myfunc}
            from file import get_side_value, side_{myfunc}
            from fractions import Fraction
            def conanfile_func():
                return get_value(), {myfunc}(), get_side_value(), side_{myfunc}(), str(Fraction(1,1))
        """)
        expected_return = (value, myfunc, value, myfunc, "1")

        tmp = temp_folder()
        with chdir(tmp):
            save("conanfile.py", conanfile.format(value=value, myfunc=myfunc, subdir=subdir_name))
            save("file.py", side_content.format(value=value, myfunc=myfunc))
            save("{}/api.py".format(subdir_name), subdir_content.format(value=value, myfunc=myfunc))
            if add_subdir_init:
                save("__init__.py", "")
                save("{}/__init__.py".format(subdir_name), "")

        loaded, module_id = _parse_conanfile(os.path.join(tmp, "conanfile.py"))
        return loaded, module_id, expected_return

    @parameterized.expand([(True, False), (False, True), (False, False)])
    @unittest.skipIf(six.PY2, "Python 2 requires __init__.py file in modules")
    def test_py3_recipe_colliding_init_filenames(self, sub1, sub2):
        myfunc1, value1 = "recipe1", 42
        myfunc2, value2 = "recipe2", 23
        loaded1, module_id1, exp_ret1 = self._create_and_load(myfunc1, value1, "subdir", sub1)
        loaded2, module_id2, exp_ret2 = self._create_and_load(myfunc2, value2, "subdir", sub2)

        self.assertNotEqual(module_id1, module_id2)
        self.assertEqual(loaded1.conanfile_func(), exp_ret1)
        self.assertEqual(loaded2.conanfile_func(), exp_ret2)

    def test_recipe_colliding_filenames(self):
        myfunc1, value1 = "recipe1", 42
        myfunc2, value2 = "recipe2", 23
        loaded1, module_id1, exp_ret1 = self._create_and_load(myfunc1, value1, "subdir", True)
        loaded2, module_id2, exp_ret2 = self._create_and_load(myfunc2, value2, "subdir", True)

        self.assertNotEqual(module_id1, module_id2)
        self.assertEqual(loaded1.conanfile_func(), exp_ret1)
        self.assertEqual(loaded2.conanfile_func(), exp_ret2)

    @parameterized.expand([(True, ), (False, )])
    def test_wrong_imports(self, add_subdir_init):
        myfunc1, value1 = "recipe1", 42

        # Item imported does not exist, but file exists
        with six.assertRaisesRegex(self, ConanException, "Unable to load conanfile in"):
            self._create_and_load(myfunc1, value1, "requests", add_subdir_init)

        # File does not exists in already existing module
        with six.assertRaisesRegex(self, ConanException, "Unable to load conanfile in"):
            self._create_and_load(myfunc1, value1, "conans", add_subdir_init)

    def test_helpers_python_library(self):
        mylogger = """
value = ""
def append(data):
    global value
    value += data
"""
        temp = temp_folder()
        save(os.path.join(temp, "myconanlogger.py"), mylogger)

        conanfile = "import myconanlogger"
        temp1 = temp_folder()
        save(os.path.join(temp1, "conanfile.py"), conanfile)
        temp2 = temp_folder()
        save(os.path.join(temp2, "conanfile.py"), conanfile)

        try:
            sys.path.append(temp)
            loaded1, _ = _parse_conanfile(os.path.join(temp1, "conanfile.py"))
            loaded2, _ = _parse_conanfile(os.path.join(temp2, "conanfile.py"))
            self.assertIs(loaded1.myconanlogger, loaded2.myconanlogger)
            self.assertIs(loaded1.myconanlogger.value, loaded2.myconanlogger.value)
        finally:
            sys.path.remove(temp)
