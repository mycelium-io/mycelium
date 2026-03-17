---
name: tdd
description: Test-driven development workflow. Use when the user says /tdd or wants to build a feature test-first. Guides red-green-refactor cycle.
---

# Test-Driven Development

Guide the user through a red-green-refactor TDD cycle.

## Workflow

1. **Clarify** — Ask the user what feature or fix they want to build. Understand the expected behavior.

2. **Write failing test** — Write a test that describes the desired behavior. The test should be specific and minimal.

3. **Run test (red)** — Run the test to confirm it fails:
   ```bash
   cd fastapi-backend && python -m pytest tests/<test_file>.py -x -q
   ```
   Show the failure output. This is the "red" phase.

4. **Implement** — Write the minimum code to make the test pass. No more, no less.

5. **Run test (green)** — Run the test again to confirm it passes. This is the "green" phase.

6. **Refactor** — If the implementation can be improved, refactor while keeping the test green.

7. **Full suite** — Run the full test suite to ensure nothing else broke:
   ```bash
   cd fastapi-backend && python -m pytest tests/ -x -q
   ```

8. **Repeat** — Ask if the user wants to add another test case or move on.
