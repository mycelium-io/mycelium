// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A small JSON Schema validator for the subset of OpenAPI 3.1 that FastAPI emits.
 *
 * Test-only. It exists so the mock fixtures can be checked against the committed
 * `openapi.json` without pulling a schema library into the app's dependency tree
 * — the same reasoning that keeps `scripts/check_workflows.py` on the standard
 * library. The subset is what the spec actually uses: `$ref`, `anyOf`, `allOf`,
 * `type`, `properties`/`required`, `items`, `additionalProperties`, `enum`.
 * Anything outside it (`format`, `minLength`, numeric bounds) is presentation or
 * a constraint a fixture can't plausibly get wrong, and is ignored on purpose.
 *
 * Errors accumulate with the JSON path that produced them, because "the mock is
 * wrong" is not an actionable failure — "`nodes[0].inbound` is a string, the
 * spec says integer" is.
 */

export interface Schema {
  $ref?: string;
  anyOf?: Schema[];
  oneOf?: Schema[];
  allOf?: Schema[];
  type?: string | string[];
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
  additionalProperties?: Schema | boolean;
  enum?: unknown[];
}

export interface Spec {
  paths: Record<string, Record<string, unknown>>;
  components?: { schemas?: Record<string, Schema> };
}

/** Options that change what counts as a violation. */
export interface ValidateOptions {
  /**
   * Report properties the schema doesn't declare. The spec permits them
   * (pydantic models don't set `additionalProperties: false`), but a mock
   * carrying a field the backend never sends is a field the UI can be built
   * against and then lose in production — which is the drift worth catching.
   */
  rejectUnknownProperties?: boolean;
}

function deref(schema: Schema, spec: Spec): Schema {
  let current = schema;
  // Nested `$ref`s are legal; the spec's are one deep, but follow the chain.
  while (current.$ref) {
    const name = current.$ref.replace("#/components/schemas/", "");
    const target = spec.components?.schemas?.[name];
    if (!target) throw new Error(`unresolvable $ref: ${current.$ref}`);
    current = target;
  }
  return current;
}

function typeName(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "object") return "object";
  return typeof value;
}

function typeMatches(value: unknown, expected: string): boolean {
  const actual = typeName(value);
  // JSON has one number type; an integer is a valid `number`.
  if (expected === "number") return actual === "number" || actual === "integer";
  return actual === expected;
}

/**
 * Validate `value` against `schema`, returning one message per violation.
 * An empty array means the value conforms.
 */
export function validate(
  value: unknown,
  schema: Schema,
  spec: Spec,
  options: ValidateOptions = {},
  path = "$",
): string[] {
  const node = deref(schema, spec);

  if (node.allOf) return node.allOf.flatMap((s) => validate(value, s, spec, options, path));

  const union = node.anyOf ?? node.oneOf;
  if (union) {
    // A union is satisfied by any branch; report only that none matched, since
    // the per-branch errors of a 6-way `anyOf` are noise, not a diagnosis.
    const matched = union.some((s) => validate(value, s, spec, options, path).length === 0);
    return matched ? [] : [`${path}: matches no branch of anyOf (got ${typeName(value)})`];
  }

  if (node.enum && !node.enum.includes(value)) {
    return [`${path}: ${JSON.stringify(value)} is not one of ${JSON.stringify(node.enum)}`];
  }

  if (node.type) {
    const allowed = Array.isArray(node.type) ? node.type : [node.type];
    if (!allowed.some((t) => typeMatches(value, t))) {
      return [`${path}: expected ${allowed.join("|")}, got ${typeName(value)}`];
    }
  }

  const errors: string[] = [];

  if (Array.isArray(value) && node.items) {
    value.forEach((item, i) => {
      errors.push(...validate(item, node.items as Schema, spec, options, `${path}[${i}]`));
    });
    return errors;
  }

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const record = value as Record<string, unknown>;
    for (const key of node.required ?? []) {
      if (!(key in record)) errors.push(`${path}.${key}: required by the spec, missing`);
    }
    for (const [key, child] of Object.entries(record)) {
      const declared = node.properties?.[key];
      if (declared) {
        errors.push(...validate(child, declared, spec, options, `${path}.${key}`));
      } else if (typeof node.additionalProperties === "object") {
        errors.push(...validate(child, node.additionalProperties, spec, options, `${path}.${key}`));
      } else if (
        options.rejectUnknownProperties &&
        node.properties &&
        node.additionalProperties !== true
      ) {
        errors.push(`${path}.${key}: not declared by the spec`);
      }
    }
  }

  return errors;
}

/** The `application/json` schema an operation declares for one status code. */
export function statusSchema(operation: unknown, status: number): Schema | null {
  const responses = (operation as { responses?: Record<string, unknown> })?.responses;
  const declared = responses?.[String(status)] as
    | { content?: { "application/json"?: { schema?: Schema } } }
    | undefined;
  return declared?.content?.["application/json"]?.schema ?? null;
}

/** The 200 `application/json` schema for an operation, or null if it has none. */
export function successSchema(operation: unknown): Schema | null {
  return statusSchema(operation, 200);
}
