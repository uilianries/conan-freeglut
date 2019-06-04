
from collections import namedtuple

import six
from parameterized import parameterized

from conans.errors import ConanException
from conans.model.ref import ConanFileReference
from conans.model.requires import Requirements
from conans.test.unittests.model.transitive_reqs_test import GraphTest
from conans.test.utils.conanfile import TestConanFile
from conans.test.utils.tools import test_processed_profile


def _get_nodes(graph, name):
    """ return all the nodes matching a particular name. Could be >1 in case
    that private requirements embed different versions
    """
    return [n for n in graph.nodes if n.conanfile.name == name]


Edge = namedtuple("Edge", "src dst")


def _get_edges(graph):
    edges = set()
    for n in graph.nodes:
        edges.update([Edge(n, neigh) for neigh in n.neighbors()])
    return edges


def _clear_revs(requires):
    for require in requires.values():
        require.ref = require.ref.copy_clear_rev()
    return requires


class VersionRangesTest(GraphTest):

    def setUp(self):
        super(VersionRangesTest, self).setUp()

        for v in ["0.1", "0.2", "0.3", "1.1", "1.1.2", "1.2.1", "2.1", "2.2.1"]:
            say_content = TestConanFile("Say", v)
            say_ref = ConanFileReference.loads("Say/%s@myuser/testing" % v)
            self.retriever.save_recipe(say_ref, say_content)

    def build_graph(self, content, update=False):
        self.loader.cached_conanfiles = {}
        processed_profile = test_processed_profile()
        root_conan = self.retriever.root(str(content), processed_profile)
        deps_graph = self.builder.load_graph(root_conan, update, update, self.remotes,
                                             processed_profile)
        self.output.write("\n".join(self.resolver.output))
        return deps_graph

    def test_local_basic(self):
        for expr, solution in [(">0.0", "2.2.1"),
                               (">0.1,<1", "0.3"),
                               (">0.1,<1||2.1", "2.1"),
                               ("", "2.2.1"),
                               ("~0", "0.3"),
                               ("~=1", "1.2.1"),
                               ("~1.1", "1.1.2"),
                               ("~=2", "2.2.1"),
                               ("~=2.1", "2.1"),
                               ]:
            deps_graph = self.build_graph(TestConanFile("Hello", "1.2",
                                                        requires=["Say/[%s]@myuser/testing" % expr]))

            self.assertEqual(2, len(deps_graph.nodes))
            hello = _get_nodes(deps_graph, "Hello")[0]
            say = _get_nodes(deps_graph, "Say")[0]
            self.assertEqual(_get_edges(deps_graph), {Edge(hello, say)})

            self.assertEqual(hello.ref, None)
            conanfile = hello.conanfile
            self.assertEqual(conanfile.version, "1.2")
            self.assertEqual(conanfile.name, "Hello")
            say_ref = ConanFileReference.loads("Say/%s@myuser/testing" % solution)
            self.assertEqual(_clear_revs(conanfile.requires), Requirements(str(say_ref)))

    def test_remote_basic(self):
        self.resolver._local_search = None
        remote_packages = []
        for v in ["0.1", "0.2", "0.3", "1.1", "1.1.2", "1.2.1", "2.1", "2.2.1"]:
            say_ref = ConanFileReference.loads("Say/[%s]@myuser/testing" % v)
            remote_packages.append(say_ref)
        self.remotes.add("myremote", "myurl")
        self.remote_manager.packages = remote_packages
        for expr, solution in [(">0.0", "2.2.1"),
                               (">0.1,<1", "0.3"),
                               (">0.1,<1||2.1", "2.1"),
                               ("", "2.2.1"),
                               ("~0", "0.3"),
                               ("~=1", "1.2.1"),
                               ("~1.1", "1.1.2"),
                               ("~=2", "2.2.1"),
                               ("~=2.1", "2.1"),
                               ]:
            deps_graph = self.build_graph(TestConanFile("Hello", "1.2",
                                                        requires=["Say/[%s]@myuser/testing" % expr]),
                                          update=True)
            self.assertEqual(self.remote_manager.count, {'Say/*@myuser/testing': 1})
            self.assertEqual(2, len(deps_graph.nodes))
            hello = _get_nodes(deps_graph, "Hello")[0]
            say = _get_nodes(deps_graph, "Say")[0]
            self.assertEqual(_get_edges(deps_graph), {Edge(hello, say)})

            self.assertEqual(hello.ref, None)
            conanfile = hello.conanfile
            self.assertEqual(conanfile.version, "1.2")
            self.assertEqual(conanfile.name, "Hello")
            say_ref = ConanFileReference.loads("Say/%s@myuser/testing" % solution)
            self.assertEqual(_clear_revs(conanfile.requires), Requirements(str(say_ref)))

    def test_remote_optimized(self):
        self.resolver._local_search = None
        remote_packages = []
        self.remotes.add("myremote", "myurl")
        for v in ["0.1", "0.2", "0.3", "1.1", "1.1.2", "1.2.1", "2.1", "2.2.1"]:
            say_ref = ConanFileReference.loads("Say/%s@myuser/testing" % v)
            remote_packages.append(say_ref)
        self.remote_manager.packages = remote_packages

        dep_content = """from conans import ConanFile
class Dep1Conan(ConanFile):
    requires = "Say/[%s]@myuser/testing"
"""
        dep_ref = ConanFileReference.loads("Dep1/0.1@myuser/testing")
        self.retriever.save_recipe(dep_ref, dep_content % ">=0.1")
        dep_ref = ConanFileReference.loads("Dep2/0.1@myuser/testing")
        self.retriever.save_recipe(dep_ref, dep_content % ">=0.1")

        hello_content = """from conans import ConanFile
class HelloConan(ConanFile):
    name = "Hello"
    requires = "Dep1/0.1@myuser/testing", "Dep2/0.1@myuser/testing"
"""
        deps_graph = self.build_graph(hello_content, update=True)
        self.assertEqual(4, len(deps_graph.nodes))
        hello = _get_nodes(deps_graph, "Hello")[0]
        say = _get_nodes(deps_graph, "Say")[0]
        dep1 = _get_nodes(deps_graph, "Dep1")[0]
        dep2 = _get_nodes(deps_graph, "Dep2")[0]
        self.assertEqual(_get_edges(deps_graph), {Edge(hello, dep1), Edge(hello, dep2),
                                                  Edge(dep1, say), Edge(dep2, say)})

        # Most important check: counter of calls to remote
        self.assertEqual(self.remote_manager.count, {'Say/*@myuser/testing': 1})

    @parameterized.expand([("", "0.3", None, None),
                           ('"Say/1.1@myuser/testing"', "1.1", False, False),
                           ('"Say/0.2@myuser/testing"', "0.2", False, True),
                           ('("Say/1.1@myuser/testing", "override")', "1.1", True, False),
                           ('("Say/0.2@myuser/testing", "override")', "0.2", True, True),
                           # ranges
                           ('"Say/[<=1.2]@myuser/testing"', "1.2.1", False, False),
                           ('"Say/[>=0.2,<=1.0]@myuser/testing"', "0.3", False, True),
                           ('"Say/[>=0.2 <=1.0]@myuser/testing"', "0.3", False, True),
                           ('("Say/[<=1.2]@myuser/testing", "override")', "1.2.1", True, False),
                           ('("Say/[>=0.2,<=1.0]@myuser/testing", "override")', "0.3", True, True),
                           ('("Say/[>=0.2 <=1.0]@myuser/testing", "override")', "0.3", True, True),
                           ])
    def transitive_test(self, version_range, solution, override, valid):
        hello_text = TestConanFile("Hello", "1.2",
                                   requires=["Say/[>0.1, <1]@myuser/testing"])
        hello_ref = ConanFileReference.loads("Hello/1.2@myuser/testing")
        self.retriever.save_recipe(hello_ref, hello_text)

        chat_content = """
from conans import ConanFile

class ChatConan(ConanFile):
    name = "Chat"
    version = "2.3"
    requires = "Hello/1.2@myuser/testing", %s
"""
        if valid is False:
            with six.assertRaisesRegex(self, ConanException, "not valid"):
                self.build_graph(chat_content % version_range)
            return

        deps_graph = self.build_graph(chat_content % version_range)
        hello = _get_nodes(deps_graph, "Hello")[0]
        say = _get_nodes(deps_graph, "Say")[0]
        chat = _get_nodes(deps_graph, "Chat")[0]
        edges = {Edge(hello, say), Edge(chat, hello)}
        if override is not None:
            self.assertIn("overridden", self.output)
        else:
            self.assertNotIn("overridden", self.output)
        if override is False:
            edges = {Edge(hello, say), Edge(chat, say), Edge(chat, hello)}

        if valid is True:
            self.assertIn(" valid", self.output)
            self.assertNotIn("not valid", self.output)
        elif valid is False:
            self.assertIn("not valid", self.output)
        self.assertEqual(3, len(deps_graph.nodes))

        self.assertEqual(_get_edges(deps_graph), edges)

        self.assertEqual(hello.ref.copy_clear_rev(), hello_ref)
        conanfile = hello.conanfile
        self.assertEqual(conanfile.version, "1.2")
        self.assertEqual(conanfile.name, "Hello")
        say_ref = ConanFileReference.loads("Say/%s@myuser/testing" % solution)
        self.assertEqual(_clear_revs(conanfile.requires), Requirements(str(say_ref)))

    def duplicated_error_test(self):
        content = TestConanFile("log4cpp", "1.1.1")
        log4cpp_ref = ConanFileReference.loads("log4cpp/1.1.1@myuser/testing")
        self.retriever.save_recipe(log4cpp_ref, content)

        content = """
from conans import ConanFile

class LoggerInterfaceConan(ConanFile):
    name = "LoggerInterface"
    version = "0.1.1"

    def requirements(self):
        self.requires("log4cpp/[~1.1]@myuser/testing")
"""
        logiface_ref = ConanFileReference.loads("LoggerInterface/0.1.1@myuser/testing")
        self.retriever.save_recipe(logiface_ref, content)

        content = """
from conans import ConanFile

class OtherConan(ConanFile):
    name = "other"
    version = "2.0.11549"
    requires = "LoggerInterface/[~0.1]@myuser/testing"
"""
        other_ref = ConanFileReference.loads("other/2.0.11549@myuser/testing")
        self.retriever.save_recipe(other_ref, content)

        content = """
from conans import ConanFile

class Project(ConanFile):
    requires = "LoggerInterface/[~0.1]@myuser/testing", "other/[~2.0]@myuser/testing"
"""
        deps_graph = self.build_graph(content)

        log4cpp = _get_nodes(deps_graph, "log4cpp")[0]
        logger_interface = _get_nodes(deps_graph, "LoggerInterface")[0]
        other = _get_nodes(deps_graph, "other")[0]

        self.assertEqual(4, len(deps_graph.nodes))

        self.assertEqual(log4cpp.ref.copy_clear_rev(), log4cpp_ref)
        conanfile = log4cpp.conanfile
        self.assertEqual(conanfile.version, "1.1.1")
        self.assertEqual(conanfile.name, "log4cpp")

        self.assertEqual(logger_interface.ref.copy_clear_rev(), logiface_ref)
        conanfile = logger_interface.conanfile
        self.assertEqual(conanfile.version, "0.1.1")
        self.assertEqual(conanfile.name, "LoggerInterface")

        self.assertEqual(other.ref.copy_clear_rev(), other_ref)
        conanfile = other.conanfile
        self.assertEqual(conanfile.version, "2.0.11549")
        self.assertEqual(conanfile.name, "other")
