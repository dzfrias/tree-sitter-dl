# tree-sitter-dl

tree-sitter-dl is a simple Python script to help replace the archived
[nvim-treesitter](https://github.com/nvim-treesitter/nvim-treesitter). It should
work with recent versions of Python 3. To run it, you must have the following
programs on your computer:

- git
- [tree-sitter](https://tree-sitter.github.io/tree-sitter/creating-parsers/1-getting-started.html)

Using the script is simple. To install:

```
./tree-sitter-dl.py install python zig rust
```

This will also automatically update the listed parsers. To uninstall:

```
./tree-sitter-dl.py uninstall python zig rust
```

If you would like to install specific parsers:

```
./tree-sitter-dl.py install python:https://github.com/tree-sitter/tree-sitter-python@v0.25.0 zig:https://github.com/GrayJack/tree-sitter-zig
```

Use the `--help` flag for all options. The default install location will be your
config directory. For example, on macOS, this is `~/.config/nvim`. Note that in
order to enable syntax highlighting, you must run `vim.treesitter.start()`
somewhere in your configuration.

Indentation, folding, and other niceities **will not work**; those features were
provided by nvim-treesitter, not built-in to Neovim.

Read [my blog post](https://dzfrias.dev/blog/tree-sitter-post-archival) for more
information.

# License

This program is licensed under the [MIT license](/LICENSE).
