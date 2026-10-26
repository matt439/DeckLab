"""Typed product tokens/set-tokens commands; no private data is written to Git."""
import json

from decklab.lib import accessories, inventory
from decklab.lib.inventory import kit, ops_products

from . import product_kit


def show(args):
    inv = inventory.current()
    row = ops_products.product_row(inv, args.stem)
    data = {"stem": args.stem, "name": accessories._product_title(inv, f"{args.stem}.csv"),
            **{key: row.text(key).strip() for key in ("status", "intact", "token_cards")},
            "sha256": kit.status_sha256(inv), "tokens_sha256": ops_products.token_sha256(inv)}
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"{data['name']}: {data['token_cards'] or '(packing not recorded)'}")
        print(f"sha {data['sha256']} (give it to set-tokens as --expect)")
        print(f"tokens sha {data['tokens_sha256'] or 'none'} (give it as --tokens-sha256)")
    return 0


def save(args):
    from . import inv_orders
    inv = inventory.current()
    sha = product_kit._expected(inv, args.expect)
    token_sha = None if args.tokens_sha256 == "none" else args.tokens_sha256
    op = inventory.Op(ops_products.KIND, {"stem": args.stem, "sha256": sha,
                      "tokens_sha256": token_sha, "token_cards": args.tokens})
    return inv_orders._run(args, op)
