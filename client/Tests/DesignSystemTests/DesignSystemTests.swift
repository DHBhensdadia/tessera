import Testing

@testable import DesignSystem

// Part 1 has no design in it to test. What this asserts is that the test target exists,
// resolves the module, and runs in the gates — because a suite that is not wired in is
// discovered to be missing at the moment it was supposed to catch something.
@Test func theModuleIsReachableFromItsTests() {
    #expect(!designSystemVersion.isEmpty)
}
