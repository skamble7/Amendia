// GENERATED — DO NOT HAND-EDIT.
// Run `npm run gen:api` to regenerate the registry types from its live OpenAPI document.
// `npm run gen:api:check` fails when this file drifts from the running API.

export interface paths {
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Health */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Capabilities */
        get: operations["list_capabilities_capabilities_get"];
        put?: never;
        /** Register Capability */
        post: operations["register_capability_capabilities_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capabilities/{capability_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Capability Versions */
        get: operations["list_capability_versions_capabilities__capability_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capabilities/{capability_id}/{version}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Capability */
        get: operations["get_capability_capabilities__capability_id___version__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/capabilities/{capability_id}/{version}/deprecate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Deprecate Capability */
        post: operations["deprecate_capability_capabilities__capability_id___version__deprecate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifact-schemas": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Artifact Schemas */
        get: operations["list_artifact_schemas_artifact_schemas_get"];
        put?: never;
        /** Register Artifact Schema */
        post: operations["register_artifact_schema_artifact_schemas_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifact-schemas/{artifact_key}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Artifact Schema Versions */
        get: operations["list_artifact_schema_versions_artifact_schemas__artifact_key__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifact-schemas/{artifact_key}/{version}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Artifact Schema */
        get: operations["get_artifact_schema_artifact_schemas__artifact_key___version__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifact-schemas/{artifact_key}/{version}/deprecate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Deprecate Artifact Schema */
        post: operations["deprecate_artifact_schema_artifact_schemas__artifact_key___version__deprecate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Packs */
        get: operations["list_packs_packs_get"];
        put?: never;
        /** Submit Pack */
        post: operations["submit_pack_packs_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}/bpmn": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pack Bpmn */
        get: operations["get_pack_bpmn_packs__pack_key___version__bpmn_get"];
        /** Upload Bpmn */
        put: operations["upload_bpmn_packs__pack_key___version__bpmn_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Validate Pack */
        post: operations["validate_pack_packs__pack_key___version__validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}/activate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Activate Pack */
        post: operations["activate_pack_packs__pack_key___version__activate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}/deprecate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Deprecate Pack */
        post: operations["deprecate_pack_packs__pack_key___version__deprecate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Pack Versions */
        get: operations["list_pack_versions_packs__pack_key__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pack */
        get: operations["get_pack_packs__pack_key___version__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}/validation-report": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Validation Report */
        get: operations["get_validation_report_packs__pack_key___version__validation_report_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/packs/{pack_key}/{version}/resolution": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pack Resolution */
        get: operations["get_pack_resolution_packs__pack_key___version__resolution_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/resolve": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Resolve */
        post: operations["resolve_resolve_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AllPredicate */
        "AllPredicate-Input": {
            /** All */
            all: (components["schemas"]["AllPredicate-Input"] | components["schemas"]["AnyPredicate-Input"] | components["schemas"]["NotPredicate-Input"] | components["schemas"]["LeafPredicate"])[];
        };
        /** AllPredicate */
        "AllPredicate-Output": {
            /** All */
            all: (components["schemas"]["AllPredicate-Output"] | components["schemas"]["AnyPredicate-Output"] | components["schemas"]["NotPredicate-Output"] | components["schemas"]["LeafPredicate"])[];
        };
        /** AnyPredicate */
        "AnyPredicate-Input": {
            /** Any */
            any: (components["schemas"]["AllPredicate-Input"] | components["schemas"]["AnyPredicate-Input"] | components["schemas"]["NotPredicate-Input"] | components["schemas"]["LeafPredicate"])[];
        };
        /** AnyPredicate */
        "AnyPredicate-Output": {
            /** Any */
            any: (components["schemas"]["AllPredicate-Output"] | components["schemas"]["AnyPredicate-Output"] | components["schemas"]["NotPredicate-Output"] | components["schemas"]["LeafPredicate"])[];
        };
        /** ArtifactIO */
        ArtifactIO: {
            /** Name */
            name: string;
            /**
             * ArtifactRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example art.payment.draft_repair@^1.0.0
             */
            schema: string;
            /**
             * Required
             * @default true
             */
            required: boolean;
        };
        /** ArtifactSchemaRegistration */
        ArtifactSchemaRegistration: {
            /** Created At */
            created_at?: string | null;
            /** Updated At */
            updated_at?: string | null;
            /** Artifact Key */
            artifact_key: string;
            /** Version */
            version: string;
            /** Title */
            title: string;
            /** Description */
            description?: string | null;
            /** Json Schema */
            json_schema: {
                [key: string]: unknown;
            };
            /** @default backward */
            compatibility: components["schemas"]["Compatibility"];
            /** Tags */
            tags?: string[] | null;
            status: components["schemas"]["ArtifactStatus"];
        };
        /**
         * ArtifactStatus
         * @enum {string}
         */
        ArtifactStatus: "active" | "deprecated";
        /** Binding */
        Binding: {
            /** Element Id */
            element_id: string;
            /**
             * Element Kind
             * @enum {string}
             */
            element_kind: "serviceTask" | "userTask";
            /** Executor */
            executor: components["schemas"]["CapabilityExecutor"] | components["schemas"]["HumanExecutor"];
            hitl: components["schemas"]["Hitl"];
            /** Inputs */
            inputs?: components["schemas"]["ArtifactIO"][];
            /** Outputs */
            outputs?: components["schemas"]["ArtifactIO"][];
        };
        /** CapabilityDescriptor */
        CapabilityDescriptor: {
            /** Created At */
            created_at?: string | null;
            /** Updated At */
            updated_at?: string | null;
            /**
             * Descriptor Version
             * @constant
             */
            descriptor_version: "1.0";
            /** Capability Id */
            capability_id: string;
            /** Version */
            version: string;
            /** Title */
            title: string;
            /** Description */
            description?: string | null;
            kind: components["schemas"]["CapabilityKind"];
            side_effect: components["schemas"]["SideEffect"];
            /** Idempotent */
            idempotent?: boolean | null;
            /** Inputs */
            inputs: components["schemas"]["SchemaIO"][];
            /** Outputs */
            outputs: components["schemas"]["SchemaIO"][];
            /** Config Schema */
            config_schema?: {
                [key: string]: unknown;
            } | null;
            /** Runtime */
            runtime: components["schemas"]["SkillRuntime"] | components["schemas"]["McpRuntime"] | components["schemas"]["LlmRuntime"];
            constraints?: components["schemas"]["Constraints"] | null;
            /** Owner */
            owner?: string | null;
            status: components["schemas"]["CapabilityStatus"];
        };
        /** CapabilityExecutor */
        CapabilityExecutor: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "capability";
            /**
             * CapabilityRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example cap.payment.draft_repair@^1.0.0
             */
            capability: string;
        };
        /**
         * CapabilityKind
         * @enum {string}
         */
        CapabilityKind: "skill" | "mcp" | "llm";
        /**
         * CapabilityStatus
         * @enum {string}
         */
        CapabilityStatus: "active" | "deprecated";
        /**
         * Compatibility
         * @enum {string}
         */
        Compatibility: "backward" | "none";
        /** Constraints */
        Constraints: {
            /**
             * Timeout Seconds
             * @default 120
             */
            timeout_seconds: number;
            /**
             * Max Retries
             * @default 2
             */
            max_retries: number;
            min_hitl_mode?: components["schemas"]["HitlMode"] | null;
        };
        /** GatewayVariable */
        GatewayVariable: {
            /** Gateway Id */
            gateway_id: string;
            /**
             * Variable
             * @description e.g. beneficiary.repair_verdict
             */
            variable: string;
            /** Source Artifact */
            source_artifact: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** Hitl */
        Hitl: {
            mode: components["schemas"]["HitlMode"];
            /** Role */
            role?: string | null;
        };
        /**
         * HitlMode
         * @enum {string}
         */
        HitlMode: "none" | "review_after" | "approve_result" | "approve_actions" | "manual";
        /** HumanExecutor */
        HumanExecutor: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "human";
            /** Role */
            role: string;
            /** Assist Capability */
            assist_capability?: string | null;
        };
        /**
         * LeafOp
         * @enum {string}
         */
        LeafOp: "eq" | "ne" | "in" | "starts_with" | "intersects" | "exists" | "gt" | "gte" | "lt" | "lte";
        /** LeafPredicate */
        LeafPredicate: {
            /** Field */
            field: string;
            op: components["schemas"]["LeafOp"];
            /** Value */
            value?: unknown;
        };
        /** LlmRuntime */
        LlmRuntime: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "llm";
            /** Prompt Key */
            prompt_key: string;
            /** Model Config Key */
            model_config_key?: string | null;
            /**
             * Structured Output
             * @default true
             */
            structured_output: boolean;
        };
        /** McpRuntime */
        McpRuntime: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "mcp";
            /** Server Key */
            server_key: string;
            /** Tools */
            tools: string[];
            /** @default streamable_http */
            transport: components["schemas"]["McpTransport"];
        };
        /**
         * McpTransport
         * @enum {string}
         */
        McpTransport: "streamable_http" | "stdio" | "sse";
        /** NotPredicate */
        "NotPredicate-Input": {
            /** Not */
            not: components["schemas"]["AllPredicate-Input"] | components["schemas"]["AnyPredicate-Input"] | components["schemas"]["NotPredicate-Input"] | components["schemas"]["LeafPredicate"];
        };
        /** NotPredicate */
        "NotPredicate-Output": {
            /** Not */
            not: components["schemas"]["AllPredicate-Output"] | components["schemas"]["AnyPredicate-Output"] | components["schemas"]["NotPredicate-Output"] | components["schemas"]["LeafPredicate"];
        };
        /**
         * PackStatus
         * @enum {string}
         */
        PackStatus: "draft" | "validated" | "active" | "deprecated";
        /** Policies */
        Policies: {
            /** Separation Of Duties */
            separation_of_duties?: components["schemas"]["SeparationOfDuties"][] | null;
        };
        /** ProcessPackManifest */
        "ProcessPackManifest-Input": {
            /** Created At */
            created_at?: string | null;
            /** Updated At */
            updated_at?: string | null;
            /**
             * Manifest Version
             * @constant
             */
            manifest_version: "1.0";
            /** Pack Key */
            pack_key: string;
            /** Version */
            version: string;
            /** Title */
            title: string;
            /** Description */
            description?: string | null;
            process: components["schemas"]["ProcessRef"];
            /** Triage Rules */
            triage_rules: components["schemas"]["TriageRule-Input"][];
            /** Requires Capabilities */
            requires_capabilities: components["schemas"]["RequiresCapability"][];
            /** Artifacts */
            artifacts: string[];
            /** Bindings */
            bindings: components["schemas"]["Binding"][];
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["GatewayVariable"][] | null;
            policies?: components["schemas"]["Policies"] | null;
            status: components["schemas"]["PackStatus"];
            /** Created By */
            created_by?: string | null;
        };
        /** ProcessPackManifest */
        "ProcessPackManifest-Output": {
            /** Created At */
            created_at?: string | null;
            /** Updated At */
            updated_at?: string | null;
            /**
             * Manifest Version
             * @constant
             */
            manifest_version: "1.0";
            /** Pack Key */
            pack_key: string;
            /** Version */
            version: string;
            /** Title */
            title: string;
            /** Description */
            description?: string | null;
            process: components["schemas"]["ProcessRef"];
            /** Triage Rules */
            triage_rules: components["schemas"]["TriageRule-Output"][];
            /** Requires Capabilities */
            requires_capabilities: components["schemas"]["RequiresCapability"][];
            /** Artifacts */
            artifacts: string[];
            /** Bindings */
            bindings: components["schemas"]["Binding"][];
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["GatewayVariable"][] | null;
            policies?: components["schemas"]["Policies"] | null;
            status: components["schemas"]["PackStatus"];
            /** Created By */
            created_by?: string | null;
        };
        /** ProcessRef */
        ProcessRef: {
            /** Bpmn File */
            bpmn_file: string;
            /** Process Id */
            process_id: string;
            /** Bpmn Sha256 */
            bpmn_sha256: string;
        };
        /** RequiresCapability */
        RequiresCapability: {
            /**
             * CapabilityRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example cap.payment.draft_repair@^1.0.0
             */
            ref: string;
            /**
             * Resolved
             * @description Pinned by the registry at activation; absent while draft
             */
            resolved?: string | null;
        };
        /** ResolveRequest */
        ResolveRequest: {
            /** Envelope */
            envelope: {
                [key: string]: unknown;
            };
        };
        /** ResolveResponse */
        ResolveResponse: {
            /** Pack Key */
            pack_key: string;
            /** Pack Version */
            pack_version: string;
            /** Rule Id */
            rule_id: string;
            /**
             * Resolved At
             * Format: date-time
             */
            resolved_at?: string;
        };
        /**
         * SchemaIO
         * @description A named input/output bound to a versioned artifact schema.
         */
        SchemaIO: {
            /** Name */
            name: string;
            /**
             * ArtifactRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example art.payment.draft_repair@^1.0.0
             */
            schema: string;
            /**
             * Required
             * @default true
             */
            required: boolean;
        };
        /** SeparationOfDuties */
        SeparationOfDuties: {
            /**
             * Constraint
             * @constant
             */
            constraint: "distinct_actor";
            /** Elements */
            elements: string[];
        };
        /**
         * SideEffect
         * @enum {string}
         */
        SideEffect: "read_only" | "side_effectful";
        /** SkillRuntime */
        SkillRuntime: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "skill";
            /** Entrypoint */
            entrypoint: string;
        };
        /** TriageRule */
        "TriageRule-Input": {
            /** Rule Id */
            rule_id: string;
            /**
             * Priority
             * @description Lower number wins when multiple packs match
             */
            priority: number;
            /** Description */
            description?: string | null;
            /** When */
            when: components["schemas"]["AllPredicate-Input"] | components["schemas"]["AnyPredicate-Input"] | components["schemas"]["NotPredicate-Input"] | components["schemas"]["LeafPredicate"];
        };
        /** TriageRule */
        "TriageRule-Output": {
            /** Rule Id */
            rule_id: string;
            /**
             * Priority
             * @description Lower number wins when multiple packs match
             */
            priority: number;
            /** Description */
            description?: string | null;
            /** When */
            when: components["schemas"]["AllPredicate-Output"] | components["schemas"]["AnyPredicate-Output"] | components["schemas"]["NotPredicate-Output"] | components["schemas"]["LeafPredicate"];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    list_capabilities_capabilities_get: {
        parameters: {
            query?: {
                status?: string | null;
                kind?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapabilityDescriptor"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_capability_capabilities_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CapabilityDescriptor"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapabilityDescriptor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_capability_versions_capabilities__capability_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                capability_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapabilityDescriptor"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_capability_capabilities__capability_id___version__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                capability_id: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapabilityDescriptor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deprecate_capability_capabilities__capability_id___version__deprecate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                capability_id: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CapabilityDescriptor"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_artifact_schemas_artifact_schemas_get: {
        parameters: {
            query?: {
                status?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactSchemaRegistration"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_artifact_schema_artifact_schemas_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ArtifactSchemaRegistration"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactSchemaRegistration"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_artifact_schema_versions_artifact_schemas__artifact_key__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactSchemaRegistration"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_artifact_schema_artifact_schemas__artifact_key___version__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactSchemaRegistration"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deprecate_artifact_schema_artifact_schemas__artifact_key___version__deprecate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactSchemaRegistration"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_packs_packs_get: {
        parameters: {
            query?: {
                status?: string | null;
                limit?: number;
                offset?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessPackManifest-Output"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    submit_pack_packs_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProcessPackManifest-Input"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessPackManifest-Output"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_pack_bpmn_packs__pack_key___version__bpmn_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_bpmn_packs__pack_key___version__bpmn_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_pack_packs__pack_key___version__validate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    activate_pack_packs__pack_key___version__activate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessPackManifest-Output"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deprecate_pack_packs__pack_key___version__deprecate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessPackManifest-Output"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_pack_versions_packs__pack_key__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessPackManifest-Output"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_pack_packs__pack_key___version__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProcessPackManifest-Output"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_validation_report_packs__pack_key___version__validation_report_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_pack_resolution_packs__pack_key___version__resolution_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                pack_key: string;
                version: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resolve_resolve_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ResolveRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ResolveResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}
