-- qsql language server client for Neovim — native vim.lsp, no plugins required.
--
-- Load it directly:            :luafile /path/to/editors/nvim/qsql.lua
-- or from init.lua (if placed on your runtimepath as lua/qsql.lua):
--                              require("qsql")
--
-- The server must be on PATH:  uv tool install 'qsql-demo[lsp]'
--                              (or: pipx install 'qsql-demo[lsp]')
-- so that `qsql lsp` runs. Diagnostics publish on open/change; column completion
-- is served over omnifunc — trigger it with <C-x><C-o> (or any LSP completion
-- plugin). Go-to-definition on a ref('cell') jumps to that cell.

-- 1) filetype: *.qsql and *.qsql.sql are qsql notebooks
vim.filetype.add({
  extension = { qsql = "qsql" },
  pattern = { [".*%.qsql%.sql"] = "qsql" },
})

-- 2) one client per project root, started for every qsql buffer
local group = vim.api.nvim_create_augroup("qsql_lsp", { clear = true })
vim.api.nvim_create_autocmd("FileType", {
  group = group,
  pattern = "qsql",
  callback = function(args)
    -- borrow SQL syntax highlighting while keeping the qsql filetype for LSP
    vim.bo[args.buf].syntax = "sql"

    local dir = vim.fs.dirname(vim.api.nvim_buf_get_name(args.buf))
    -- a qsqlrc.py or base.qsql marks the project root; else the file's dir
    local marker = vim.fs.find({ "qsqlrc.py", "base.qsql" }, { upward = true, path = dir })[1]
    local root = marker and vim.fs.dirname(marker) or dir

    vim.lsp.start({
      name = "qsql",
      cmd = { "qsql", "lsp" },
      root_dir = root,
    })
  end,
})

-- nvim-lspconfig variant (if you'd rather register a named server):
--   require("lspconfig.configs").qsql = {
--     default_config = {
--       cmd = { "qsql", "lsp" },
--       filetypes = { "qsql" },
--       root_dir = require("lspconfig.util").root_pattern("qsqlrc.py", "base.qsql"),
--     },
--   }
--   require("lspconfig").qsql.setup({})
