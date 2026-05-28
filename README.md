# tree-sitter-dl

`tree-sitter-dl.py` is a simple Python script that helps replace the archived
[nvim-treesitter](https://github.com/nvim-treesitter/nvim-treesitter). It
manages the installation of
[tree-sitter](https://tree-sitter.github.io/tree-sitter/) parsers for
[Neovim](https://neovim.io/). It should work with recent versions of Python 3.
To run it, you must have the following programs on your computer:

- git
- [tree-sitter CLI](https://tree-sitter.github.io/tree-sitter/creating-parsers/1-getting-started.html)

Using the script is simple. To install parsers:

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
config directory. For example, on macOS, this is `~/.config/nvim`.

Neovim supports tree-sitter highlighting and folding out of the box. You can
enable them with the following lines in your `ftplugin/*` files (that have
corresponding Neovim parsers):

```lua
vim.treesitter.start()
vim.wo[0][0].foldexpr = 'v:lua.vim.treesitter.foldexpr()'
vim.wo[0][0].foldmethod = 'expr'
```

Note that tree-sitter indentation **will not work**, as it was provided by
nvim-treesitter.

Read [my blog post](https://dzfrias.dev/blog/tree-sitter-dl) for more
information.

# Why tree-sitter-dl?

There are many Neovim-related tree-sitter parser managers. Why use a Python
script? Here are a couple reasons:

- It is independent of Neovim version
- tree-sitter-dl focuses on safety: don't install parsers without trusting them
  first
- CLI interfaces are more consistent than Neovim interfaces
- This script isn't meant to fall out of date or require heavy maintainance over
  time

If these sound appealing to you, give tree-sitter-dl a try!

# License

This program is licensed under the [MIT license](/LICENSE).
