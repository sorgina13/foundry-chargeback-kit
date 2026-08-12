"""Insert request-ID propagation into an existing APIM policy without disturbing the rest.

The existing policy is treated as the source of truth. This script only adds the
correlation headers, then verifies that no pre-existing element (notably the
token-limit block) was lost. Review the generated policy before deploying it.

Usage:
    python apply_policy.py --source exported-policy.xml --backend-id my-backend
"""
import argparse
import json
import pathlib
import re
import sys

MARKER = "chargeback correlation"

INBOUND_ADDITION = (
    f"\r\n\t\t\t\t<!-- {MARKER}: mint/forward correlation key -->"
    "\r\n\t\t\t\t<set-variable name=\"requestId\" value=\"@(context.Request.Headers.GetValueOrDefault(&quot;x-request-id&quot;, context.RequestId.ToString()))\" />"
    "\r\n\t\t\t\t<set-header name=\"x-request-id\" exists-action=\"override\">"
    "\r\n\t\t\t\t\t<value>@((string)context.Variables[&quot;requestId&quot;])</value>"
    "\r\n\t\t\t\t</set-header>"
    "\r\n\t\t\t\t<set-header name=\"x-cost-centre\" exists-action=\"skip\">"
    "\r\n\t\t\t\t\t<value>@(context.Request.Headers.GetValueOrDefault(&quot;x-cost-centre&quot;, &quot;unattributed&quot;))</value>"
    "\r\n\t\t\t\t</set-header>"
)

OUTBOUND_ADDITION = (
    f"\r\n\t\t\t<!-- {MARKER}: echo so the client can join without trusting upstream -->"
    "\r\n\t\t\t<set-header name=\"x-request-id\" exists-action=\"override\">"
    "\r\n\t\t\t\t<value>@((string)context.Variables[&quot;requestId&quot;])</value>"
    "\r\n\t\t\t</set-header>"
)

# Whitespace and line endings vary (tabs plus CRLF), so match structurally.
OUTBOUND_RE = re.compile(r"(<outbound>\s*<base />)(\s*</outbound>)")

# Elements that must survive the patch untouched.
PRESERVED_MARKERS = ("llm-token-limit", "set-backend-service", "<on-error>")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=pathlib.Path,
        required=True,
        help="Exported APIM policy to patch. Never commit a policy containing secrets.",
    )
    parser.add_argument(
        "--backend-id",
        required=True,
        help="backend-id of the set-backend-service element used as the inbound anchor.",
    )
    parser.add_argument("--out-xml", type=pathlib.Path, default=pathlib.Path("policy-merged.xml"))
    parser.add_argument("--out-body", type=pathlib.Path, default=pathlib.Path("policy-body.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    xml = args.source.read_text(encoding="utf-8")

    anchor = f'<set-backend-service id="apim-generated-policy" backend-id="{args.backend_id}" />'
    if xml.count(anchor) != 1:
        return fail(f"inbound anchor found {xml.count(anchor)} times; aborting")
    if len(OUTBOUND_RE.findall(xml)) != 1:
        return fail(f"outbound block matched {len(OUTBOUND_RE.findall(xml))} times; aborting")
    if MARKER in xml:
        return fail("policy already contains the chargeback additions; aborting")

    patched = xml.replace(anchor, anchor + INBOUND_ADDITION, 1)
    patched = OUTBOUND_RE.sub(lambda m: m.group(1) + OUTBOUND_ADDITION + m.group(2), patched, count=1)

    for marker in PRESERVED_MARKERS:
        if patched.count(marker) < xml.count(marker):
            return fail(f"marker '{marker}' lost during patch; aborting")

    args.out_xml.write_text(patched, encoding="utf-8")
    args.out_body.write_text(
        json.dumps({"properties": {"format": "rawxml", "value": patched}}),
        encoding="utf-8",
    )

    print(f"original bytes : {len(xml)}")
    print(f"patched bytes  : {len(patched)}")
    print(f"llm-token-limit occurrences preserved: {patched.count('llm-token-limit')}")
    print(f"wrote {args.out_xml} and {args.out_body}")
    print("Review the generated policy before deploying it.")
    return 0


def fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
