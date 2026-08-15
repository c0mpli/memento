# Homebrew formula template for Memento.
#
# This is a template: fill in `url` (a release tarball or a git tag) and its
# `sha256`, host it in your own tap (e.g. `yourname/homebrew-tap`), then:
#
#     brew tap yourname/tap
#     brew install memento
#     memento init && memento start
#
# `brew install memento` gives you the `memento` command; `memento start`
# installs the LaunchAgent so background capture runs at login.
class Memento < Formula
  include Language::Python::Virtualenv

  desc "Local-first ambient memory for your Mac, queryable from Claude Code/Codex via MCP"
  homepage "https://github.com/yourname/memento"
  url "https://github.com/yourname/memento/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_TARBALL_SHA256"
  license "MIT"

  depends_on "python@3.12"

  # `brew update-python-resources` will populate resource blocks for `mcp`
  # and its dependencies here.

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "memento", shell_output("#{bin}/memento --version")
  end
end
