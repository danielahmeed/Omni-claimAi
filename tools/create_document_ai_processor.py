#!/usr/bin/env python3
"""Create (or find) a Document AI Invoice Parser processor and print its name.

The printed name is the value for DOCUMENT_AI_PROCESSOR. Running the script
again reuses the processor with the same display name instead of creating a
second one.

Usage:
    gcloud auth application-default login
    python tools/create_document_ai_processor.py --project my-project [--location us]

Needs the Document AI API enabled (gcloud services enable documentai.googleapis.com)
and permission to create processors (for example the Document AI Editor role).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INVOICE_PROCESSOR = "INVOICE_PROCESSOR"


def make_client(location: str):
    from google.api_core.client_options import ClientOptions
    from google.cloud import documentai

    return documentai.DocumentProcessorServiceClient(
        client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com"), transport="rest")


def ensure_processor(client, project: str, location: str, display_name: str) -> tuple[str, bool]:
    """Return (processor name, created?)."""
    from google.cloud import documentai

    parent = f"projects/{project}/locations/{location}"
    for processor in client.list_processors(parent=parent):
        if processor.display_name == display_name and processor.type_ == INVOICE_PROCESSOR:
            return processor.name, False
    processor = client.create_processor(
        parent=parent, processor=documentai.Processor(type_=INVOICE_PROCESSOR, display_name=display_name))
    return processor.name, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument("--location", default="us", choices=["us", "eu"], help="Document AI location (default: us)")
    parser.add_argument("--name", default="omniclaim-invoice-parser", help="Processor display name")
    args = parser.parse_args()

    name, created = ensure_processor(make_client(args.location), args.project, args.location, args.name)
    print(("Created" if created else "Found existing") + f" Invoice Parser processor:\n{name}")
    print(f"\nSet DOCUMENT_AI_PROCESSOR={name}")


if __name__ == "__main__":
    main()
