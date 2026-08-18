import DesignSystem

// Every component, in every state, in both colour schemes, with the accessibility
// settings toggleable — the thing a person looks at to judge whether the design system
// is any good. That judgement is the one part of this phase no test replaces.
//
// A command-line entry point for now: part 3 turns it into a window. It is already a
// target so the gates compile it from the first commit, which is what stops it drifting
// behind the components it is supposed to display.
print("Tessera design system \(DesignSystem.version) — gallery arrives in 3.1 part 3")
