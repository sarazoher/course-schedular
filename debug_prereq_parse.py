from config import Config
from utils.course_catalog import load_catalog, build_resolver
from utils.req_parser import parse_req_text
from collections import Counter


if __name__ == "__main__":
    catalog = load_catalog(Config.CATALOG_DIR)
    resolve = build_resolver(catalog)

    parsed = 0
    unknown_tokens = Counter()
    unknown_examples = {}   # token -> example "COURSECODE - coursename"

    for c in catalog:
        if not getattr(c, "prereq_text", None):
            continue

        tree = parse_req_text(c.prereq_text, resolve)
        parsed += 1

        # count unknown leaves
        def walk(node):
            if node is None:
                return
            
            if node.__class__.__name__ == "ReqLeaf":
                if node.code is None:
                    tok = (node.raw or "").strip()
                    if tok:
                        unknown_tokens[tok] += 1
                        unknown_examples.setdefault(tok, f"{c.code} - {c.name}")
                return

            for child in node.items:
                walk(child)

        walk(tree)

    print("Courses with prereq_text parsed:", parsed)
    print("Unknown prereq tokens:", sum(unknown_tokens.values()))

    print("\nTop unknown tokens:")
    for tok, cnt in unknown_tokens.most_common(20):
        example = unknown_examples.get(tok, "")
        print(f"{cnt:>3} x {tok}   (e.g. {example})")
