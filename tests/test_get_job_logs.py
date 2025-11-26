import io
import zipfile

from main import _decode_zipped_job_logs


def test_decode_zipped_job_logs_combines_entries():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zip_file:
        zip_file.writestr("b.txt", "second line")
        zip_file.writestr("a.txt", "first line")

    result = _decode_zipped_job_logs(buffer.getvalue())

    assert result == "[a.txt]\nfirst line\n\n[b.txt]\nsecond line"


def test_decode_zipped_job_logs_handles_invalid_zip():
    assert _decode_zipped_job_logs(b"not-a-zip") == ""
