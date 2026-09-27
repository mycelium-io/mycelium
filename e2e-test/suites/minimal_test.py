"""Minimal test to verify pyATS task subprocess works."""

from pyats import aetest


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def check(self):
        self.passed("Setup OK")


class SimpleTest(aetest.Testcase):
    @aetest.test
    def test_pass(self):
        self.passed("Hello from minimal test")


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def check(self):
        self.passed("Cleanup OK")


if __name__ == "__main__":
    aetest.main()
