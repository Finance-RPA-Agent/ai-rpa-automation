"""Per-tool JSON generation contracts, bound to observed file and column IDs."""
import copy
import re

from product.data_tools import SPECS


def wants_difference_chart(instruction):
    return bool(re.search(r"\b(?:difference|variance|delta)\s+(?:bar\s+|line\s+)?chart\b|\bchart\s+(?:of|showing)\s+(?:the\s+)?(?:amount\s+)?differences?\b|(?:金额差异|金额差额).*?(?:图|chart)", instruction, re.I))


def expanded_schema(model):
    source = model.model_json_schema()
    definitions = source.get("$defs", {})
    def expand(value):
        if isinstance(value, list): return [expand(item) for item in value]
        if not isinstance(value, dict): return value
        if "$ref" in value:
            return expand(definitions[value["$ref"].rsplit("/", 1)[-1]])
        return {key: expand(item) for key, item in value.items() if key not in ("$defs", "title", "default")}
    return expand(source)


def action_schema(context):
    frames = context.get("_frame_catalog", context.get("frames", []))
    ids = [frame["id"] for frame in frames]
    columns = list(dict.fromkeys(column for frame in frames for column in frame["columns"]))
    files = [file["file_id"] for file in context.get("files", [])]
    variants = []
    def branch(tool, arguments):
        return {"type": "object", "additionalProperties": False,
                "required": ["action", "tool", "arguments", "message"],
                "properties": {"action": {"type": "string", "enum": ["tool"]},
                               "tool": {"type": "string", "enum": [tool]}, "arguments": arguments,
                               "message": {"type": "string", "enum": [""]}}}
    for tool, (model, _) in SPECS.items():
        schema = expanded_schema(model)
        properties = schema.get("properties", {})
        if "frame_id" in properties and not ids: continue
        if tool in ("concatenate", "join_tables") and len(ids) < 2: continue
        if tool == "export_report" and not ids: continue
        if tool == "inspect_table" and not files: continue
        for key in ("frame_id", "left_id", "right_id"):
            if key in properties: properties[key]["enum"] = ids
        if "frame_ids" in properties: properties["frame_ids"]["items"]["enum"] = ids
        if "file_id" in properties: properties["file_id"]["enum"] = files
        if tool == "create_chart":
            for frame in frames:
                if not 1 <= frame.get("rows", 1) <= 30: continue
                allowed = frame.get("difference_columns", []) if context.get("difference_chart_required") else frame["columns"]
                if not allowed: continue
                args = copy.deepcopy(schema); props = args["properties"]
                props["frame_id"]["enum"] = [frame["id"]]
                props["x"]["enum"] = frame["columns"]
                props["y"]["enum"] = allowed
                variants.append(branch(tool, args))
            continue
        if tool == "aggregate":
            # Bind each metrics input to the selected frame. Output aliases stay new names.
            for frame in frames:
                args = copy.deepcopy(schema); props = args["properties"]
                props["frame_id"]["enum"] = [frame["id"]]
                props["group_by"]["items"]["enum"] = frame["columns"]
                props["metrics"]["items"]["properties"]["column"]["enum"] = frame["columns"]
                args["required"] = ["frame_id", "group_by", "metrics"]
                variants.append(branch(tool, args))
            continue
        for key in ("columns", "by", "keys", "left_on", "right_on"):
            if key in properties: properties[key]["items"]["enum"] = columns
        if tool == "derive_column":
            properties["left"]["enum"] = columns
            properties["right"] = {"anyOf": [{"type": "string", "enum": columns}, {"type": "null"}]}
        if tool == "filter_rows":
            properties["conditions"]["items"]["properties"]["column"]["enum"] = columns
        if tool == "create_chart":
            properties["x"]["enum"] = columns; properties["y"]["enum"] = columns
        variants.append(branch(tool, schema))
    for action in ("final", "ask"):
        variants.append({"type": "object", "additionalProperties": False,
            "required": ["action", "tool", "arguments", "message"],
            "properties": {"action": {"type": "string", "enum": [action]}, "tool": {"type": "null"},
                           "arguments": {"type": "object", "properties": {}, "additionalProperties": False},
                           "message": {"type": "string", "minLength": 1, "maxLength": 1600}}})
    return {"anyOf": variants}
