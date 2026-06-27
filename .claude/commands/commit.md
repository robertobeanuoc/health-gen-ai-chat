# Conventional Commit

Create a git commit following the [Conventional Commits](https://www.conventionalcommits.org/) specification.

## Format

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

## Types

| Type | Use when |
|------|----------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no logic change |
| `refactor` | Code restructure, no feature/fix |
| `perf` | Performance improvement |
| `test` | Adding or updating tests |
| `chore` | Build, deps, config, tooling |
| `ci` | CI/CD pipeline changes |

## Scope (this project)

Use the affected module: `server`, `mcp-exec`, `mcp-semantic`, `mcp-viz`, `dbt`, `config`, `deps`, `env`.

## Steps

1. Run `git diff --cached` and `git status` to see all staged changes.
2. If nothing is staged, stage the relevant files first.
3. Draft a message: type and scope from the table above, imperative short description (<72 chars), body only when the *why* needs more context.
4. Commit with:

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <description>

[body if needed]

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

## Rules

- Description in imperative mood ("add", "fix", "remove" — not "added", "fixes")
- No period at the end of the description line
- Breaking changes: append `!` after scope → `feat(server)!: ...` and add `BREAKING CHANGE:` footer
- Keep description under 72 characters
