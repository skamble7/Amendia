import { Badge } from "@/components/ui/badge";
import { schemaType, type JsonSchema } from "@/components/artifact/schema";
import { cn } from "@/lib/utils";

/** Render a JSON Schema as a field tree with type + required markers + enums. */
export function SchemaTree({ schema, depth = 0 }: { schema: JsonSchema; depth?: number }) {
  const t = schemaType(schema);
  if (t === "object" && schema.properties) {
    const required = new Set(schema.required ?? []);
    return (
      <ul className={cn("space-y-1", depth > 0 && "ml-4 border-l border-border pl-3")}>
        {Object.entries(schema.properties).map(([key, propSchema]) => (
          <SchemaField key={key} name={key} schema={propSchema} required={required.has(key)} depth={depth} />
        ))}
      </ul>
    );
  }
  if (t === "array" && schema.items) {
    return <SchemaTree schema={schema.items} depth={depth} />;
  }
  return null;
}

function SchemaField({ name, schema, required, depth }: { name: string; schema: JsonSchema; required: boolean; depth: number }) {
  const t = schemaType(schema);
  const nested = (t === "object" && schema.properties) || (t === "array" && schema.items);
  return (
    <li>
      <div className="flex items-center gap-2 py-0.5 text-sm">
        <span className="font-mono">{name}</span>
        {required && <span className="text-danger" title="required">*</span>}
        <Badge variant="outline" className="text-[10px]">{t === "array" ? `${schemaType(schema.items)}[]` : t}</Badge>
        {schema.enum && (
          <span className="flex flex-wrap gap-1">
            {schema.enum.map((e) => (
              <Badge key={String(e)} variant="artifact" className="text-[10px]">{String(e)}</Badge>
            ))}
          </span>
        )}
        {schema.description && <span className="truncate text-xs text-muted-foreground">{schema.description}</span>}
      </div>
      {nested && <SchemaTree schema={t === "array" ? schema.items! : schema} depth={depth + 1} />}
    </li>
  );
}
