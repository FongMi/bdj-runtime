"""Run the actual probe cleanup on aliased directories with a host JDK."""

import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


class CandidateCleanupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        java_home = os.environ.get("JAVA_HOME")
        javac = pathlib.Path(java_home) / "bin" / ("javac.exe" if os.name == "nt" else "javac") if java_home else shutil.which("javac")
        if not javac or not pathlib.Path(javac).is_file():
            raise unittest.SkipTest("Set JAVA_HOME to run the host Java filesystem regression")
        cls.java = pathlib.Path(javac).with_name("java.exe" if os.name == "nt" else "java")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = pathlib.Path(cls.directory.name)
        activity = pathlib.Path(__file__).with_name("ProbeActivity.java").read_text(encoding="utf-8")
        start = activity.index("File filesDir = getFilesDir();")
        end = activity.index("extract(root);", start)
        setup = activity[start:end].replace("getFilesDir()", "aliasDirectory")
        setup = re.sub(r"Log\.i\(.*?\);", "", setup, flags=re.S)
        start = activity.index("private static void removeCandidate(")
        end = activity.index("private static void verifyJvm(", start)
        cleanup = activity[start:end]
        source = """import java.io.File;
public final class CandidateCleanupRegression {
  private static File candidateRoot(File aliasDirectory) throws Exception {
SETUP
    return root;
  }
CLEANUP
  public static void main(String[] args) throws Exception {
    if (args[0].equals("failure")) {
      File failure = new File("failed-file") {
        public boolean isDirectory() { return false; }
        public boolean delete() { return false; }
      };
      try {
        removeCandidate(failure);
        throw new AssertionError("A failed delete was accepted");
      } catch (IllegalStateException expected) {
        if (!expected.getMessage().contains("Cannot remove stale candidate file")) throw expected;
      }
      return;
    }
    final File physicalParent = new File(args[2]).getCanonicalFile();
    // Windows File canonicalization retains junctions; model Android's resolved
    // filesDir contract while exercising the actual source and real filesystem.
    File aliasDirectory = new File(args[1]) {
      public File getCanonicalFile() { return physicalParent; }
    };
    File root = candidateRoot(aliasDirectory);
    File expected = new File(physicalParent, "candidate");
    if (!root.getAbsoluteFile().equals(expected)) {
      throw new AssertionError("Candidate root did not canonicalize its trusted parent");
    }
    File target = root;
    if (args[0].equals("leaf")) {
      final File linkedDirectory = new File(args[3]).getCanonicalFile();
      target = new File(root.getPath()) {
        public File getCanonicalFile() { return linkedDirectory; }
        public File[] listFiles() { throw new AssertionError("A leaf link was traversed"); }
      };
    }
    removeCandidate(target);
    if (root.exists()) throw new AssertionError("Stale candidate survived cleanup");
    if (!new File(args[1]).isDirectory()) throw new AssertionError("Trusted parent alias was removed");
    if (args[0].equals("leaf") && !new File(args[3], "keep.txt").isFile()) {
      throw new AssertionError("Candidate leaf link target was traversed or deleted");
    }
  }
}
""".replace("SETUP", setup).replace("CLEANUP", cleanup)
        harness = cls.root / "CandidateCleanupRegression.java"
        harness.write_text(source, encoding="utf-8")
        subprocess.run([str(javac), "-d", str(cls.root), str(harness)], check=True)

    def link(self, alias, target):
        if os.name == "nt":
            # Junctions reproduce Android's directory ancestor aliases without symlink privileges.
            environment = {**os.environ, "BDJ_TEST_ALIAS": str(alias), "BDJ_TEST_TARGET": str(target)}
            command = ("New-Item -ItemType Junction -Path $env:BDJ_TEST_ALIAS "
                       "-Target $env:BDJ_TEST_TARGET -ErrorAction Stop | Out-Null")
            subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                           check=True, env=environment)
        else:
            alias.symlink_to(target, target_is_directory=True)

    def test_stale_nested_candidate_below_aliased_files_directory_is_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            actual, alias = root / "files", root / "alias"
            stale = actual / "candidate" / "nested" / "stale.txt"
            stale.parent.mkdir(parents=True)
            stale.write_text("stale")
            self.link(alias, actual)
            subprocess.run([str(self.java), "-cp", str(self.root), "CandidateCleanupRegression",
                            "stale", str(alias), str(actual)], check=True)
            self.assertFalse((actual / "candidate").exists())

    def test_candidate_leaf_link_is_removed_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            actual, alias, sibling = root / "files", root / "alias", root / "sibling"
            actual.mkdir()
            sibling.mkdir()
            (sibling / "keep.txt").write_text("preserve")
            self.link(alias, actual)
            self.link(actual / "candidate", sibling)
            subprocess.run([str(self.java), "-cp", str(self.root), "CandidateCleanupRegression",
                            "leaf", str(alias), str(actual), str(sibling)], check=True)
            self.assertEqual((sibling / "keep.txt").read_text(), "preserve")

    def test_deletion_failure_propagates(self):
        subprocess.run([str(self.java), "-cp", str(self.root), "CandidateCleanupRegression", "failure"], check=True)


if __name__ == "__main__":
    unittest.main()
