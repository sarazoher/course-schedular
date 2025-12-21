from config import Config
from utils.course_catalog import load_catalog, build_resolver
from utils.req_parser import parse_req_text

if __name__ == "__main__":
    catalog = load_catalog(Config.CATALOG_DIR)
    resolve = build_resolver(catalog)

    parsed = 0
    unknown = {"count": 0}

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
                    unknown["count"] += 1
                return
            for child in node.items:
                walk(child)


        walk(tree)

    print("Courses with prereq_text parsed:", parsed)
    print("Unknown prereq tokens:", unknown["count"])
