import { z } from "zod";
import { schemaType, type JsonSchema } from "./schema";

/**
 * Derive a zod validator from a (simple, convention-following) artifact JSON
 * Schema: required fields, enums, string/number/integer/boolean, nested objects
 * and arrays. This mirrors the checks the backend re-runs on edit_and_approve /
 * manual submissions; the backend remains authoritative (surface its 400 detail
 * on mismatch), this is fast client-side feedback.
 */
export function zodFromSchema(schema: JsonSchema | undefined): z.ZodTypeAny {
  if (!schema) return z.any();
  const t = schemaType(schema);

  switch (t) {
    case "object": {
      const shape: Record<string, z.ZodTypeAny> = {};
      const required = new Set(schema.required ?? []);
      for (const [key, propSchema] of Object.entries(schema.properties ?? {})) {
        let field = zodFromSchema(propSchema);
        if (!required.has(key)) field = field.optional().nullable();
        shape[key] = field;
      }
      // objects are closed by convention (additionalProperties:false); keep
      // passthrough off so unexpected keys surface, matching the backend.
      return z.object(shape);
    }
    case "array":
      return z.array(zodFromSchema(schema.items));
    case "string": {
      if (schema.enum) return z.enum(schema.enum.map(String) as [string, ...string[]]);
      // required-ness is enforced by the parent object's `required` set; a bare
      // required string still must be non-empty.
      return typeof schema.minLength === "number" ? z.string().min(schema.minLength) : z.string();
    }
    case "number":
    case "integer": {
      let n = z.coerce.number();
      if (typeof schema.minimum === "number") n = n.min(schema.minimum);
      if (typeof schema.maximum === "number") n = n.max(schema.maximum);
      return n;
    }
    case "boolean":
      return z.boolean();
    default:
      return z.any();
  }
}
