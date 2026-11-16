# google-apps-scripts-docset

Scripts to generate a [docset bundle](https://kapeli.com/docsets) from [Google Apps Scripts' reference documentation](https://developers.google.com/apps-script/reference).

## Usage

Using a tool that can handle [PEP-723](https://peps.python.org/pep-0723/) compliant scripts (like
[uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/stable/)):

1. Run [fetch.py](fetch.py) to download the documentation into `./cache`.
2. Run [build.py](build.py) to generate a `.docset` bundle from the files in `./cache`.
3. Add the newly created `GoogleAppsScript.docset` to your document browser.

## Acknowledging AI Use

This software was written with assistance from the following AI models:

- Claude Sonnet 5.5 (Anthropic)

## License

This software is licensed under the terms of the [MIT license](LICENSE).
