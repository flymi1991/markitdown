# MarkItDown Video/ASR Edition

> [!TIP]
> This package is based on Microsoft's open-source MarkItDown and adds Bilibili/YouTube video-to-Markdown, local SenseVoice ASR, and optional OpenAI-compatible LLM transcript correction.
>
> For more information, and full documentation, see the project [README.md](https://github.com/microsoft/markitdown) on GitHub.

> [!IMPORTANT]
> MarkItDown performs I/O with the privileges of the current process. Like open() or requests.get(), it will access resources that the process itself can access. Sanitize your inputs in untrusted environments, and call the narrowest `convert_*` function needed for your use case (e.g., `convert_stream()`, or `convert_local()`). See the [Security Considerations](https://github.com/microsoft/markitdown#security-considerations) section of the documentation for more information.

## Installation

From PyPI:

```bash
pip install markitdown[all]
```

From source:

```bash
git clone git@github.com:microsoft/markitdown.git
cd markitdown
pip install -e packages/markitdown[all]
```

## Usage

### Command-Line

```bash
markitdown path-to-file.pdf > document.md
```

### Python API

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert("test.xlsx")
print(result.text_content)
```

### Bilibili Video To Markdown

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert(
    "https://www.bilibili.com/video/BVxxxxxxx",
    bilibili_transcribe_audio=True,
    sensevoice_workers=8,
)
print(result.text_content)
```

The generated Markdown includes the original source URL, video metadata, description, and transcript when subtitles or audio transcription are available.

### Local SenseVoice Model

SenseVoice is used as the primary ASR backend when `funasr` is installed. The loader checks:

1. `MARKITDOWN_SENSEVOICE_MODEL`
2. `packages/markitdown/models/SenseVoiceSmall`
3. `iic/SenseVoiceSmall` via ModelScope

For portable sharing, include the SenseVoice model files in `packages/markitdown/models/SenseVoiceSmall`.

If `model.pt` is not already present, download it from ModelScope:

```text
https://www.modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt
```

Save it to:

```text
packages/markitdown/models/SenseVoiceSmall/model.pt
```

Keep the related SenseVoice config/token files in the same directory. If they are missing, download the full `iic/SenseVoiceSmall` snapshot from ModelScope or let `funasr` download it once, then copy the files into `packages/markitdown/models/SenseVoiceSmall`.

### LLM Transcript Correction

The package can auto-load OpenAI-compatible LLM settings from `markitdown_config.json`:

```json
{
  "llm": {
    "api_key": "YOUR_API_KEY",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat"
  }
}
```

When configured, Bilibili ASR transcripts are corrected with an LLM by default unless `bilibili_correct_transcript=False` is passed.

Do not commit real API keys.

### More Information

For more information, and full documentation, see the project [README.md](https://github.com/microsoft/markitdown) on GitHub.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
