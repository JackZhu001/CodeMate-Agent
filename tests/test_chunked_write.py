from codemate_agent.tools.file.write_file_chunks import WriteFileChunksTool
from codemate_agent.validation.argument_validator import ArgumentValidator


def test_write_file_chunks_writes_content(tmp_path):
    tool = WriteFileChunksTool(workspace_dir=str(tmp_path))
    result = tool.run("a/b.txt", ["hello", " ", "world"])
    assert "已成功分块写入文件" in result
    assert (tmp_path / "a/b.txt").read_text(encoding="utf-8") == "hello world"


def test_validator_rejects_too_long_write_content():
    args = {"file_path": "x.txt", "content": "a" * 4001}
    err = ArgumentValidator.validate("write_file", args)
    assert err is not None
    assert "write_file_chunks" in err


def test_validator_accepts_chunk_tool_aliases():
    args = {"file": "x.txt", "content": "abc"}
    err = ArgumentValidator.validate("write_file_chunks", args)
    assert err is None


def test_chunk_tool_no_args_returns_error_not_typeerror(tmp_path):
    tool = WriteFileChunksTool(workspace_dir=str(tmp_path))
    result = tool.run()
    assert "错误" in result
