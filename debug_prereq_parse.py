from config import Config
from utils.course_catalog import load_catalog, build_resolver
from utils.external_rules import load_external_rules
from utils.alias_rules import load_aliases_csv
from utils.req_parser import parse_req_text
from collections import Counter

from services.req_ir import ReqLeaf, ReqAnd, ReqOr


if __name__ == "__main__":
    catalog = load_catalog(Config.CATALOG_DIR)
    ext_rules = load_external_rules(Config.EXTERNAL_RULES_PATH)
    alias_rules = load_aliases_csv(Config.ALIASES_CSV_PATH)

    print("ALIASES LOADED (BEFORE PARSE):", alias_rules.alias_to_canonical)

    resolve = build_resolver(catalog, external_rules=ext_rules, alias_rules=alias_rules)

    parsed = 0
    external_tokens = Counter()
    unresolved_tokens = Counter()

    external_examples = {}  
    unresolved_examples = {}   # token -> example "COURSECODE - coursename"

    for c in catalog:
        if not getattr(c, "prereq_text", None):
            continue

        tree = parse_req_text(c.prereq_text, resolve)
        parsed += 1

        # count leaf classifications
        def walk(node):
            if node is None:
                return
            
            if isinstance(node, ReqLeaf):
                if node.code is None:
                    tok = (node.raw or "").strip()
                    if not tok:
                        return
                    if node.kind == "external":
                        external_tokens[tok] +=1
                        external_examples.setdefault(tok, f"{c.code} - {c.name}")
                    elif node.kind == "unresolved":
                        unresolved_tokens[tok] += 1
                        unresolved_examples.setdefault(tok, f"{c.code} - {c.name}")
                return

            if isinstance(node, (ReqAnd, ReqOr)):
                for child in node.items:
                    walk(child)
        walk(tree)

DEBUG = False

if DEBUG:
    print("Courses with prereq_text parsed:", parsed)
    print("External prereq tokens:", sum(external_tokens.values()))
    print("Unresolved prereq tokens:", sum(unresolved_tokens.values()))
    print("ALIASES PATH:", Config.ALIASES_CSV_PATH)
    print("ALIASES LOADED:", alias_rules.alias_to_canonical)

    print("\nTop external tokens:")
    for tok, cnt in external_tokens.most_common(20):
        example = external_examples.get(tok, "")
        print(f"{cnt:>3} x {tok}   (e.g. {example})")

    print("\nTop unresolved tokens:")
    for tok, cnt in unresolved_tokens.most_common(20):
        example = unresolved_examples.get(tok, "")
        print(f"{cnt:>3} x {tok}   (e.g. {example})")

