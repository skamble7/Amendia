// GENERATED — DO NOT HAND-EDIT.
// Run `npm run gen:api` to regenerate the runtime types from its live OpenAPI document.
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
        post?: never;
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
    "/packs/{pack_key}/{version}/bpmn": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Pack Bpmn */
        get: operations["get_pack_bpmn_packs__pack_key___version__bpmn_get"];
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
        post?: never;
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
        post?: never;
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
    "/instances": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Instances */
        get: operations["list_instances_instances_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/instances/{process_instance_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Instance */
        get: operations["get_instance_instances__process_instance_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/instances/{process_instance_id}/state": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Instance State
         * @description The current checkpointed graph state (artifacts included) — dev/debug only.
         */
        get: operations["get_instance_state_instances__process_instance_id__state_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/hitl-tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Hitl Tasks */
        get: operations["list_hitl_tasks_hitl_tasks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/hitl-tasks/{task_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Hitl Task */
        get: operations["get_hitl_task_hitl_tasks__task_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/hitl-tasks/{task_id}/claim": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Claim Task */
        post: operations["claim_task_hitl_tasks__task_id__claim_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/hitl-tasks/{task_id}/decide": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Decide Task */
        post: operations["decide_task_hitl_tasks__task_id__decide_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/admin/seed": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Seed */
        post: operations["seed_admin_seed_post"];
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
        AllPredicate: {
            /** All */
            all: (components["schemas"]["AllPredicate"] | components["schemas"]["AnyPredicate"] | components["schemas"]["NotPredicate"] | components["schemas"]["LeafPredicate"])[];
        };
        /** AnyPredicate */
        AnyPredicate: {
            /** Any */
            any: (components["schemas"]["AllPredicate"] | components["schemas"]["AnyPredicate"] | components["schemas"]["NotPredicate"] | components["schemas"]["LeafPredicate"])[];
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
        /** DecideRequest */
        DecideRequest: {
            /** Decision */
            decision: string;
            /** Comment */
            comment?: string | null;
            /** Edits */
            edits?: {
                [key: string]: unknown;
            } | null;
            /** Approved Action Ids */
            approved_action_ids?: string[] | null;
        };
        /**
         * Decision
         * @enum {string}
         */
        Decision: "approve" | "reject" | "edit_and_approve" | "return_for_rework" | "complete" | "escalate";
        /** DecisionRecord */
        DecisionRecord: {
            decision: components["schemas"]["Decision"];
            /** Decided By */
            decided_by: string;
            /**
             * Decided At
             * Format: date-time
             */
            decided_at: string;
            /** Comment */
            comment?: string | null;
            /** Edits */
            edits?: {
                [key: string]: unknown;
            } | null;
            /** Approved Action Ids */
            approved_action_ids?: string[] | null;
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
        /** HitlTask */
        HitlTask: {
            /** Created At */
            created_at?: string | null;
            /** Updated At */
            updated_at?: string | null;
            /** Task Id */
            task_id: string;
            /** Process Instance Id */
            process_instance_id: string;
            /** Pack Key */
            pack_key: string;
            /** Pack Version */
            pack_version: string;
            /** Element Id */
            element_id: string;
            /** Exception Id */
            exception_id: string;
            hitl_mode: components["schemas"]["HitlTaskMode"];
            /** Role */
            role: string;
            /** Title */
            title: string;
            /** Description */
            description?: string | null;
            /** @default normal */
            priority: components["schemas"]["TaskPriority"];
            /** Due At */
            due_at?: string | null;
            /** Assignee */
            assignee?: string | null;
            sod?: components["schemas"]["Sod"] | null;
            payload: components["schemas"]["TaskPayload"];
            /** Allowed Decisions */
            allowed_decisions: components["schemas"]["Decision"][];
            status: components["schemas"]["TaskStatus"];
            decision?: components["schemas"]["DecisionRecord"] | null;
        };
        /**
         * HitlTaskMode
         * @enum {string}
         */
        HitlTaskMode: "review_after" | "approve_result" | "approve_actions" | "manual";
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
         * InstanceStatus
         * @enum {string}
         */
        InstanceStatus: "created" | "running" | "waiting_hitl" | "completed" | "failed" | "cancelled";
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
        NotPredicate: {
            /** Not */
            not: components["schemas"]["AllPredicate"] | components["schemas"]["AnyPredicate"] | components["schemas"]["NotPredicate"] | components["schemas"]["LeafPredicate"];
        };
        /**
         * PackStatus
         * @enum {string}
         */
        PackStatus: "draft" | "validated" | "active" | "deprecated";
        /** PayloadArtifact */
        PayloadArtifact: {
            /** Name */
            name: string;
            /** Schema */
            schema: string;
            /** Data */
            data: {
                [key: string]: unknown;
            };
        };
        /** Policies */
        Policies: {
            /** Separation Of Duties */
            separation_of_duties?: components["schemas"]["SeparationOfDuties"][] | null;
        };
        /** ProcessInstance */
        ProcessInstance: {
            /** Process Instance Id */
            process_instance_id: string;
            /** Exception Id */
            exception_id: string;
            /** Pack Key */
            pack_key: string;
            /** Pack Version */
            pack_version: string;
            /** @default created */
            status: components["schemas"]["InstanceStatus"];
            /** Correlation Id */
            correlation_id: string;
            /** Idempotency Key */
            idempotency_key: string;
            /** Outcome */
            outcome?: string | null;
            /** Last Error */
            last_error?: string | null;
            /** Artifact Names */
            artifact_names?: string[];
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at?: string;
        };
        /** ProcessPackManifest */
        ProcessPackManifest: {
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
            triage_rules: components["schemas"]["TriageRule"][];
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
        /** ProposedAction */
        ProposedAction: {
            /** Action Id */
            action_id: string;
            /**
             * Kind
             * @description e.g. release_payment, send_pacs004, send_camt029
             */
            kind: string;
            /** Summary */
            summary: string;
            /** Detail */
            detail: {
                [key: string]: unknown;
            };
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
        /** Sod */
        Sod: {
            /** Excluded Users */
            excluded_users?: string[] | null;
            /** Derived From */
            derived_from?: string[] | null;
        };
        /** TaskPayload */
        TaskPayload: {
            /** Artifacts */
            artifacts?: components["schemas"]["PayloadArtifact"][] | null;
            /** Proposed Actions */
            proposed_actions?: components["schemas"]["ProposedAction"][] | null;
            /** Context Url */
            context_url?: string | null;
        };
        /**
         * TaskPriority
         * @enum {string}
         */
        TaskPriority: "low" | "normal" | "high" | "critical";
        /**
         * TaskStatus
         * @enum {string}
         */
        TaskStatus: "open" | "claimed" | "decided" | "cancelled" | "expired";
        /** TriageRule */
        TriageRule: {
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
            when: components["schemas"]["AllPredicate"] | components["schemas"]["AnyPredicate"] | components["schemas"]["NotPredicate"] | components["schemas"]["LeafPredicate"];
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
                    "application/json": components["schemas"]["ProcessPackManifest"][];
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
                    "application/json": components["schemas"]["ProcessPackManifest"][];
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
                    "application/json": components["schemas"]["ProcessPackManifest"];
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
    list_instances_instances_get: {
        parameters: {
            query?: {
                exception_id?: string | null;
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
                    "application/json": components["schemas"]["ProcessInstance"][];
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
    get_instance_instances__process_instance_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                process_instance_id: string;
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
    get_instance_state_instances__process_instance_id__state_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                process_instance_id: string;
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
    list_hitl_tasks_hitl_tasks_get: {
        parameters: {
            query?: {
                status?: string | null;
                role?: string | null;
                process_instance_id?: string | null;
                exception_id?: string | null;
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
                    "application/json": components["schemas"]["HitlTask"][];
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
    get_hitl_task_hitl_tasks__task_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
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
                    "application/json": components["schemas"]["HitlTask"];
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
    claim_task_hitl_tasks__task_id__claim_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
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
                    "application/json": components["schemas"]["HitlTask"];
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
    decide_task_hitl_tasks__task_id__decide_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DecideRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HitlTask"];
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
    seed_admin_seed_post: {
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
}
