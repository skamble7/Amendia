// GENERATED — DO NOT HAND-EDIT.
// Run `npm run gen:api` to regenerate the registry types from its live OpenAPI document.
// `npm run gen:api:check` fails when this file drifts from the running API.

export interface paths {
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
    "/capabilities/introspect-mcp": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Introspect Mcp */
        post: operations["introspect_mcp_capabilities_introspect_mcp_post"];
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
    "/onboarding": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Sessions */
        get: operations["list_sessions_onboarding_get"];
        put?: never;
        /** Create Session */
        post: operations["create_session_onboarding_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Session */
        get: operations["get_session_onboarding__session_id__get"];
        put?: never;
        post?: never;
        /** Delete Session */
        delete: operations["delete_session_onboarding__session_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/assemble": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Assemble */
        post: operations["assemble_onboarding__session_id__assemble_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/bindings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Bindings */
        put: operations["set_bindings_onboarding__session_id__bindings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/bpmn": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Attach Bpmn */
        put: operations["attach_bpmn_onboarding__session_id__bpmn_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/capabilities": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Set Capabilities */
        post: operations["set_capabilities_onboarding__session_id__capabilities_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/commit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Commit */
        post: operations["commit_onboarding__session_id__commit_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/policies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Policies */
        put: operations["set_policies_onboarding__session_id__policies_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/onboarding/{session_id}/triage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /** Set Triage */
        put: operations["set_triage_onboarding__session_id__triage_put"];
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
        /** Submit Pack */
        post: operations["submit_pack_packs_post"];
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
    "/roles": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Roles */
        get: operations["list_roles_roles_get"];
        put?: never;
        post?: never;
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
             * Required
             * @default true
             */
            required: boolean;
            /**
             * ArtifactRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example art.payment.draft_repair@^1.0.0
             */
            schema: string;
        };
        /** ArtifactSchemaRegistration */
        ArtifactSchemaRegistration: {
            /** Artifact Key */
            artifact_key: string;
            /** @default backward */
            compatibility: components["schemas"]["Compatibility"];
            /** Created At */
            created_at?: string | null;
            /** Description */
            description?: string | null;
            /** Json Schema */
            json_schema: {
                [key: string]: unknown;
            };
            status: components["schemas"]["ArtifactStatus"];
            /** Tags */
            tags?: string[] | null;
            /** Title */
            title: string;
            /** Updated At */
            updated_at?: string | null;
            /** Version */
            version: string;
        };
        /** ArtifactSeed */
        ArtifactSeed: {
            /** Source */
            source: string;
            /** Suggested Artifact Key */
            suggested_artifact_key: string;
        };
        /**
         * ArtifactStatus
         * @enum {string}
         */
        ArtifactStatus: "active" | "deprecated";
        /** AttachBpmnRequest */
        AttachBpmnRequest: {
            /** Bpmn File */
            bpmn_file?: string | null;
            /** Bpmn Xml */
            bpmn_xml: string;
        };
        /** Basics */
        Basics: {
            /**
             * Default Domain
             * @default payment
             */
            default_domain: string;
            /** Description */
            description?: string | null;
            /** Pack Key */
            pack_key: string;
            /** Title */
            title: string;
            /** Version */
            version: string;
        };
        /** Binding */
        Binding: {
            /** Element Id */
            element_id: string;
            /**
             * Element Kind
             * @enum {string}
             */
            element_kind: "serviceTask" | "userTask" | "messageCatch" | "receiveTask" | "sendTask" | "scriptTask" | "manualTask" | "businessRuleTask" | "callActivity";
            /** Executor */
            executor: components["schemas"]["CapabilityExecutor"] | components["schemas"]["HumanExecutor"] | components["schemas"]["MessageExecutor"] | components["schemas"]["CallExecutor"];
            hitl?: components["schemas"]["Hitl"] | null;
            /** Inputs */
            inputs?: components["schemas"]["ArtifactIO"][];
            /** Outputs */
            outputs?: components["schemas"]["ArtifactIO"][];
        };
        /** BindingInput */
        BindingInput: {
            /** Assist Capability Ref */
            assist_capability_ref?: string | null;
            /** Capability Ref */
            capability_ref?: string | null;
            /** Element Id */
            element_id: string;
            /** Element Kind */
            element_kind: string;
            /** Executor Type */
            executor_type: string;
            /**
             * Hitl Mode
             * @default none
             */
            hitl_mode: string;
            /** Hitl Role */
            hitl_role?: string | null;
            /** Role */
            role?: string | null;
        };
        /**
         * BpmnInventory
         * @description Parsed BPMN topology the downstream steps hang off of, plus the ADR-027 coverage report.
         */
        BpmnInventory: {
            /** Bpmn File */
            bpmn_file: string;
            /** Coverage Counts */
            coverage_counts?: {
                [key: string]: number;
            };
            /** Data Objects */
            data_objects?: components["schemas"]["DataObjectSummary"][];
            /** Documented Elements */
            documented_elements?: components["schemas"]["DocumentedElement"][];
            /** Events */
            events?: components["schemas"]["EventSummary"][];
            /** Gateway Conditions */
            gateway_conditions?: components["schemas"]["GatewayConditionSummary"][];
            /** Gateways */
            gateways?: string[];
            /** Lanes */
            lanes?: components["schemas"]["LaneSummary"][];
            /** Message Flows */
            message_flows?: components["schemas"]["MessageFlowSummary"][];
            /** Pools */
            pools?: components["schemas"]["PoolSummary"][];
            /** Process Id */
            process_id: string;
            /**
             * Required Execution Profile
             * @default common_subset
             */
            required_execution_profile: string;
            /** Service Tasks */
            service_tasks?: string[];
            /** Sha256 */
            sha256: string;
            /** Subprocesses */
            subprocesses?: components["schemas"]["SubProcessSummary"][];
            /** Task Names */
            task_names?: {
                [key: string]: string;
            };
            /** User Tasks */
            user_tasks?: string[];
        };
        /**
         * CallExecutor
         * @description ADR-039: a ``callActivity`` invokes **another pack** as a reusable sub-process (inline-compiled).
         *     ``pack`` is the callee ``pack_key``; ``version`` a semver range pinned to an exact callee version at
         *     activation (reproducible forever after). ``input_map`` maps each callee **input binding name** → a
         *     dotpath into CALLER state (the source must be produced upstream); ``output_map`` maps a **caller
         *     artifact name** → a callee **output binding name**. No HITL of its own (the callee's own HITL/SoD
         *     run inline, in the caller instance); ``side_effect`` is derived from the callee (composition is as
         *     side-effectful as what it calls).
         */
        CallExecutor: {
            /** Input Map */
            input_map?: {
                [key: string]: string;
            };
            /** Output Map */
            output_map?: {
                [key: string]: string;
            };
            /** Pack */
            pack: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "call";
            /**
             * Version
             * @default ^1.0.0
             */
            version: string;
        };
        /** CapabilityCandidate */
        CapabilityCandidate: {
            /**
             * Kind Hint
             * @default mcp
             */
            kind_hint: string;
            /**
             * Needs Endpoint
             * @default true
             */
            needs_endpoint: boolean;
            /** Source */
            source: string;
            /** Suggested Capability Id */
            suggested_capability_id: string;
        };
        /** CapabilityDescriptor */
        CapabilityDescriptor: {
            /** Capability Id */
            capability_id: string;
            /** Config Schema */
            config_schema?: {
                [key: string]: unknown;
            } | null;
            constraints?: components["schemas"]["Constraints"] | null;
            /** Created At */
            created_at?: string | null;
            /** Description */
            description?: string | null;
            /**
             * Descriptor Version
             * @constant
             */
            descriptor_version: "1.0";
            /** Idempotent */
            idempotent?: boolean | null;
            /** Inputs */
            inputs: components["schemas"]["SchemaIO"][];
            kind: components["schemas"]["CapabilityKind"];
            /** Outputs */
            outputs: components["schemas"]["SchemaIO"][];
            /** Owner */
            owner?: string | null;
            /** Runtime */
            runtime: components["schemas"]["SkillRuntime"] | components["schemas"]["McpRuntime"] | components["schemas"]["LlmRuntime"] | components["schemas"]["DeepAgentRuntime"] | components["schemas"]["DecisionRuntime"] | components["schemas"]["ReduceRuntime"];
            side_effect: components["schemas"]["SideEffect"];
            status: components["schemas"]["CapabilityStatus"];
            /** Title */
            title: string;
            /** Updated At */
            updated_at?: string | null;
            /** Version */
            version: string;
        };
        /** CapabilityExecutor */
        CapabilityExecutor: {
            /**
             * CapabilityRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example cap.payment.draft_repair@^1.0.0
             */
            capability: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "capability";
        };
        /**
         * CapabilityKind
         * @enum {string}
         */
        CapabilityKind: "skill" | "mcp" | "llm" | "deep_agent" | "decision" | "reduce";
        /**
         * CapabilityStatus
         * @enum {string}
         */
        CapabilityStatus: "active" | "deprecated";
        /**
         * CapabilityToolSelection
         * @description One selected MCP tool + operator-edited inferred ids and classification.
         */
        CapabilityToolSelection: {
            /**
             * Artifact Version
             * @default 1.0.0
             */
            artifact_version: string;
            /** Capability Id */
            capability_id?: string | null;
            /**
             * Capability Version
             * @default 1.0.0
             */
            capability_version: string;
            /** Description */
            description?: string | null;
            /** Domain */
            domain?: string | null;
            /** Endpoint */
            endpoint: string;
            /** Headers */
            headers?: {
                [key: string]: string;
            };
            /** Idempotent */
            idempotent?: boolean | null;
            /** Input Artifact Key */
            input_artifact_key?: string | null;
            /** Input Schema */
            input_schema?: {
                [key: string]: unknown;
            } | null;
            /** Min Hitl Mode */
            min_hitl_mode?: string | null;
            /** Output Artifact Key */
            output_artifact_key?: string | null;
            /** Output Schema */
            output_schema?: {
                [key: string]: unknown;
            } | null;
            /**
             * Side Effect
             * @default read_only
             */
            side_effect: string;
            /** Title */
            title?: string | null;
            /** Tool */
            tool: string;
            /**
             * Transport
             * @default streamable_http
             */
            transport: string;
        };
        /** CommitStep */
        CommitStep: {
            /** Detail */
            detail?: string | null;
            /** Key */
            key: string;
            /** Label */
            label: string;
            /**
             * Status
             * @default pending
             */
            status: string;
        };
        /**
         * Compatibility
         * @enum {string}
         */
        Compatibility: "backward" | "none";
        /** Constraints */
        Constraints: {
            /**
             * Max Retries
             * @default 2
             */
            max_retries: number;
            min_hitl_mode?: components["schemas"]["HitlMode"] | null;
            /**
             * Timeout Seconds
             * @default 120
             */
            timeout_seconds: number;
        };
        /** CreateSessionRequest */
        CreateSessionRequest: {
            /**
             * Default Domain
             * @default payment
             */
            default_domain: string;
            /** Description */
            description?: string | null;
            /** Pack Key */
            pack_key: string;
            /** Title */
            title: string;
            /** Version */
            version: string;
        };
        /** DataObjectSummary */
        DataObjectSummary: {
            /** Id */
            id: string;
            /** Name */
            name?: string | null;
        };
        /**
         * DecisionRuntime
         * @description A native DMN decision (ADR-037). The decision **table** travels inline (normalized JSON),
         *     pinned with the capability at activation — self-descriptive, like the ``mcp`` runtime (ADR-024),
         *     so no separate DMN registry. Shape: ``{hit_policy, inputs:[{expression,type?}], outputs:[{name,
         *     type?,priority_order?}], rules:[{when:[unary_test…], then:[value…], priority?}]}``. The table is
         *     parsed + structurally validated by the shared evaluator (``amendia_bpmn.dmn``) — the registry
         *     surfaces its findings as ``dmn_*`` codes, the runtime evaluates it against the bound inputs.
         */
        DecisionRuntime: {
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "decision";
            /** Table */
            table: {
                [key: string]: unknown;
            };
        };
        /**
         * DeepAgentBudget
         * @description Hard budget caging a deep_agent loop (ADR-021).
         */
        DeepAgentBudget: {
            /**
             * Max Steps
             * @default 12
             */
            max_steps: number;
            /** Max Tokens */
            max_tokens?: number | null;
        };
        /**
         * DeepAgentRuntime
         * @description A bounded Deep Agents Code loop. ``tools`` is the **whitelisted** toolset (MCP tool
         *     ids and/or named worker functions); the harness may use nothing else. ``model_config_key``
         *     should resolve to a managed/``nemoclaw`` ref. ``structured_output`` requires the harness
         *     to emit an object validating against the declared output artifact schema (host-validated).
         */
        DeepAgentRuntime: {
            budget?: components["schemas"]["DeepAgentBudget"];
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "deep_agent";
            /** Model Config Key */
            model_config_key?: string | null;
            /** Prompt Key */
            prompt_key: string;
            /**
             * Structured Output
             * @default true
             */
            structured_output: boolean;
            /** Tools */
            tools: string[];
        };
        /**
         * DocumentedElement
         * @description A retained BPMN element outside the executable set (ADR-027 coverage overlay).
         */
        DocumentedElement: {
            /** Element Id */
            element_id?: string | null;
            /** Kind */
            kind: string;
            /** Tier */
            tier: string;
        };
        /** EventSummary */
        EventSummary: {
            /** Attached To */
            attached_to?: string | null;
            /** Id */
            id: string;
            /** Name */
            name?: string | null;
            /** Subtype */
            subtype?: string | null;
        };
        /** GatewayConditionSummary */
        GatewayConditionSummary: {
            /** Flow Id */
            flow_id: string;
            /** Gateway Id */
            gateway_id: string;
            /** Raw */
            raw: string;
            /** Variable */
            variable?: string | null;
        };
        /** GatewayVariable */
        GatewayVariable: {
            /** Gateway Id */
            gateway_id: string;
            /** Source Artifact */
            source_artifact: string;
            /**
             * Variable
             * @description e.g. beneficiary.repair_verdict
             */
            variable: string;
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
            /** Assist Capability */
            assist_capability?: string | null;
            /** Role */
            role: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "human";
        };
        /** InferenceAnnotation */
        InferenceAnnotation: {
            /** Code */
            code: string;
            /** Element Id */
            element_id?: string | null;
            /** Message */
            message: string;
        };
        /** InferenceDraft */
        InferenceDraft: {
            /** Annotations */
            annotations?: components["schemas"]["InferenceAnnotation"][];
            /** Artifact Seeds */
            artifact_seeds?: components["schemas"]["ArtifactSeed"][];
            /** Bindings */
            bindings?: components["schemas"]["InferredBinding"][];
            /** Capability Candidates */
            capability_candidates?: components["schemas"]["CapabilityCandidate"][];
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["InferredGatewayVariable"][];
            /** Roles */
            roles?: components["schemas"]["InferredRole"][];
            /** Sod Candidates */
            sod_candidates?: components["schemas"]["SodCandidate"][];
        };
        /** InferredBinding */
        InferredBinding: {
            /** Element Id */
            element_id: string;
            /** Element Kind */
            element_kind: string;
            /** Executor Type */
            executor_type: string;
            /** Source Lane */
            source_lane?: string | null;
            /**
             * Suggested Hitl Mode
             * @default none
             */
            suggested_hitl_mode: string;
            /** Suggested Role */
            suggested_role?: string | null;
        };
        /** InferredGatewayVariable */
        InferredGatewayVariable: {
            /** Gateway Id */
            gateway_id: string;
            /** Variable */
            variable: string;
        };
        /** InferredRole */
        InferredRole: {
            /** Label */
            label: string;
            /** Role Id */
            role_id: string;
            /** Source Lane */
            source_lane?: string | null;
        };
        /** IntrospectMcpRequest */
        IntrospectMcpRequest: {
            /**
             * Domain
             * @default payment
             */
            domain: string;
            /** Endpoint */
            endpoint: string;
            /** Headers */
            headers?: {
                [key: string]: string;
            };
            /**
             * Transport
             * @default streamable_http
             */
            transport: string;
        };
        /** IntrospectMcpResponse */
        IntrospectMcpResponse: {
            /** Endpoint */
            endpoint: string;
            /** Tools */
            tools?: components["schemas"]["IntrospectedTool"][];
            /** Transport */
            transport: string;
        };
        /** IntrospectedTool */
        IntrospectedTool: {
            compliance: components["schemas"]["ToolCompliance"];
            /** Description */
            description?: string | null;
            /** Input Schema */
            input_schema?: {
                [key: string]: unknown;
            } | null;
            /** Name */
            name: string;
            /** Output Schema */
            output_schema?: {
                [key: string]: unknown;
            } | null;
            /** Suggested Capability Id */
            suggested_capability_id?: string | null;
            /** Suggested Input Artifact Key */
            suggested_input_artifact_key?: string | null;
            /** Suggested Output Artifact Key */
            suggested_output_artifact_key?: string | null;
        };
        /** LaneSummary */
        LaneSummary: {
            /** Id */
            id: string;
            /** Member Ids */
            member_ids?: string[];
            /** Name */
            name?: string | null;
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
            /** Model Config Key */
            model_config_key?: string | null;
            /** Prompt Key */
            prompt_key: string;
            /**
             * Structured Output
             * @default true
             */
            structured_output: boolean;
        };
        /**
         * McpRuntime
         * @description Self-descriptive MCP server binding (ADR-024). The connection details live directly on
         *     the capability descriptor — no config-forge/registry indirection.
         */
        McpRuntime: {
            /** Endpoint */
            endpoint: string;
            /** Headers */
            headers?: {
                [key: string]: string;
            };
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "mcp";
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
        /**
         * MessageExecutor
         * @description ADR-031 (Phase 2.4): the "executor" of a message catch / receive element is the external
         *     world. ``message_name`` is the business message this element awaits; correlation is by business
         *     anchor (exception_id / correlation_id) + this name — no per-pack correlation expressions.
         */
        MessageExecutor: {
            /** Message Name */
            message_name: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            type: "message";
        };
        /** MessageFlowSummary */
        MessageFlowSummary: {
            /** Id */
            id: string;
            /** Name */
            name?: string | null;
            /** Source */
            source?: string | null;
            /** Target */
            target?: string | null;
        };
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
        /** OnboardingSession */
        OnboardingSession: {
            basics: components["schemas"]["Basics"];
            /** Bindings */
            bindings?: components["schemas"]["StagedBinding"][];
            bpmn?: components["schemas"]["BpmnInventory"] | null;
            /** Commit Progress */
            commit_progress?: components["schemas"]["CommitStep"][];
            /**
             * Created At
             * Format: date-time
             */
            created_at?: string;
            /** Created By */
            created_by: string;
            /** Dry Run Report */
            dry_run_report?: {
                [key: string]: unknown;
            } | null;
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["StagedGatewayVariable"][];
            inferred?: components["schemas"]["InferenceDraft"] | null;
            /** Last Cleared */
            last_cleared?: string[];
            /** Result Pack */
            result_pack?: string | null;
            /** Reused Capability Refs */
            reused_capability_refs?: string[];
            /** Role Meta */
            role_meta?: {
                [key: string]: components["schemas"]["RoleMeta"];
            };
            /** Roles */
            roles?: string[];
            /** Session Id */
            session_id: string;
            /** Sod Policies */
            sod_policies?: components["schemas"]["StagedSod"][];
            /** Staged Artifacts */
            staged_artifacts?: components["schemas"]["StagedArtifact"][];
            /** Staged Capabilities */
            staged_capabilities?: components["schemas"]["StagedCapability"][];
            /** @default initiated */
            state: components["schemas"]["OnboardingState"];
            /** Triage Rules */
            triage_rules?: components["schemas"]["StagedTriageRule"][];
            /**
             * Updated At
             * Format: date-time
             */
            updated_at?: string;
        };
        /**
         * OnboardingState
         * @description Explicit state machine. Each transition endpoint advances (or, on an upstream
         *     edit, regresses) this. The pack lifecycle (draft→validated→active) is separate —
         *     the pack does not exist until ``commit``.
         * @enum {string}
         */
        OnboardingState: "initiated" | "bpmn_attached" | "capabilities_resolved" | "bindings_set" | "triage_set" | "policies_set" | "assembled" | "completed";
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
        /** PoolSummary */
        PoolSummary: {
            /** Id */
            id: string;
            /**
             * Is External
             * @default false
             */
            is_external: boolean;
            /** Name */
            name?: string | null;
        };
        /** ProcessPackManifest */
        "ProcessPackManifest-Input": {
            /** Artifacts */
            artifacts: string[];
            /** Bindings */
            bindings: components["schemas"]["Binding"][];
            /** Created At */
            created_at?: string | null;
            /** Created By */
            created_by?: string | null;
            /** Deep Agent Justifications */
            deep_agent_justifications?: {
                [key: string]: string;
            };
            /** Description */
            description?: string | null;
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["GatewayVariable"][] | null;
            /**
             * Manifest Version
             * @constant
             */
            manifest_version: "1.0";
            /** Pack Key */
            pack_key: string;
            policies?: components["schemas"]["Policies"] | null;
            process: components["schemas"]["ProcessRef"];
            /** Requires Capabilities */
            requires_capabilities: components["schemas"]["RequiresCapability"][];
            status: components["schemas"]["PackStatus"];
            /** Title */
            title: string;
            /** Triage Rules */
            triage_rules: components["schemas"]["TriageRule-Input"][];
            /** Updated At */
            updated_at?: string | null;
            /** Version */
            version: string;
        };
        /** ProcessPackManifest */
        "ProcessPackManifest-Output": {
            /** Artifacts */
            artifacts: string[];
            /** Bindings */
            bindings: components["schemas"]["Binding"][];
            /** Created At */
            created_at?: string | null;
            /** Created By */
            created_by?: string | null;
            /** Deep Agent Justifications */
            deep_agent_justifications?: {
                [key: string]: string;
            };
            /** Description */
            description?: string | null;
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["GatewayVariable"][] | null;
            /**
             * Manifest Version
             * @constant
             */
            manifest_version: "1.0";
            /** Pack Key */
            pack_key: string;
            policies?: components["schemas"]["Policies"] | null;
            process: components["schemas"]["ProcessRef"];
            /** Requires Capabilities */
            requires_capabilities: components["schemas"]["RequiresCapability"][];
            status: components["schemas"]["PackStatus"];
            /** Title */
            title: string;
            /** Triage Rules */
            triage_rules: components["schemas"]["TriageRule-Output"][];
            /** Updated At */
            updated_at?: string | null;
            /** Version */
            version: string;
        };
        /** ProcessRef */
        ProcessRef: {
            /** Bpmn File */
            bpmn_file: string;
            /** Bpmn Sha256 */
            bpmn_sha256: string;
            /** Process Id */
            process_id: string;
        };
        /**
         * ReduceRuntime
         * @description A collection-reduction / summary capability (ADR-038). Collapses a **list** input artifact into
         *     a scalar/summary output artifact a gateway can branch on — closing the ADR-036/037 "any/all over a
         *     list" gap. The ``config`` travels inline (normalized JSON), pinned like any capability. Shape:
         *     ``{op, source?, item_path?, predicate?, output_field}`` where ``op`` ∈ quantifiers (``any``/``all``/
         *     ``none``), ``count``, numeric (``sum``/``min``/``max``/``avg``), positional (``first``/``last``); the
         *     per-item ``predicate`` reuses the bounded DMN unary-test surface (``amendia_bpmn.dmn``) — one FEEL
         *     surface, no new mini-language. The registry surfaces its findings as ``reduce_*`` codes; the runtime
         *     evaluates it against the bound list input.
         */
        ReduceRuntime: {
            /** Config */
            config: {
                [key: string]: unknown;
            };
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "reduce";
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
            /**
             * Resolved At
             * Format: date-time
             */
            resolved_at?: string;
            /** Rule Id */
            rule_id: string;
        };
        /** RoleInUse */
        RoleInUse: {
            /** Description */
            description?: string | null;
            /** Label */
            label?: string | null;
            /** Role Id */
            role_id: string;
            /** Sources */
            sources?: string[];
        };
        /**
         * RoleMeta
         * @description Operator-authored label/description for a pack-local role id (UX/governance only).
         */
        RoleMeta: {
            /** Description */
            description?: string | null;
            /** Label */
            label?: string | null;
        };
        /**
         * SchemaIO
         * @description A named input/output bound to a versioned artifact schema.
         */
        SchemaIO: {
            /** Name */
            name: string;
            /**
             * Required
             * @default true
             */
            required: boolean;
            /**
             * ArtifactRef
             * @description Versioned reference '<id>@<range-or-pin>'.
             * @example art.payment.draft_repair@^1.0.0
             */
            schema: string;
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
        /** SetBindingsRequest */
        SetBindingsRequest: {
            /** Bindings */
            bindings?: components["schemas"]["BindingInput"][];
        };
        /** SetCapabilitiesRequest */
        SetCapabilitiesRequest: {
            /** Reused Capability Refs */
            reused_capability_refs?: string[];
            /** Tools */
            tools?: components["schemas"]["CapabilityToolSelection"][];
        };
        /** SetPoliciesRequest */
        SetPoliciesRequest: {
            /** Gateway Variables */
            gateway_variables?: components["schemas"]["StagedGatewayVariable"][];
            /** Role Meta */
            role_meta?: {
                [key: string]: components["schemas"]["RoleMeta"];
            };
            /** Roles */
            roles?: string[];
            /** Sod Policies */
            sod_policies?: components["schemas"]["StagedSod"][];
        };
        /** SetTriageRequest */
        SetTriageRequest: {
            /** Triage Rules */
            triage_rules?: components["schemas"]["StagedTriageRule"][];
        };
        /**
         * SideEffect
         * @enum {string}
         */
        SideEffect: "read_only" | "side_effectful";
        /** SkillRuntime */
        SkillRuntime: {
            /** Entrypoint */
            entrypoint: string;
            /**
             * @description discriminator enum property added by openapi-typescript
             * @enum {string}
             */
            kind: "skill";
        };
        /** SodCandidate */
        SodCandidate: {
            /** Elements */
            elements?: string[];
            /** Rationale */
            rationale: string;
        };
        /**
         * StagedArtifact
         * @description A to-be-registered artifact schema, inferred from an MCP tool's in/out schema.
         */
        StagedArtifact: {
            /** Artifact Key */
            artifact_key: string;
            /**
             * Compatibility
             * @default backward
             */
            compatibility: string;
            /** Description */
            description?: string | null;
            /** Json Schema */
            json_schema: {
                [key: string]: unknown;
            };
            /** Source Tool */
            source_tool?: string | null;
            /** Title */
            title: string;
            /** Version */
            version: string;
        };
        /** StagedBinding */
        StagedBinding: {
            /** Assist Capability Ref */
            assist_capability_ref?: string | null;
            /** Capability Ref */
            capability_ref?: string | null;
            /** Element Id */
            element_id: string;
            /** Element Kind */
            element_kind: string;
            /** Executor Type */
            executor_type: string;
            /**
             * Hitl Mode
             * @default none
             */
            hitl_mode: string;
            /** Hitl Role */
            hitl_role?: string | null;
            /** Inputs */
            inputs?: components["schemas"]["StagedBindingIO"][];
            /** Outputs */
            outputs?: components["schemas"]["StagedBindingIO"][];
            /** Role */
            role?: string | null;
        };
        /** StagedBindingIO */
        StagedBindingIO: {
            /** Name */
            name: string;
            /**
             * Required
             * @default true
             */
            required: boolean;
            /** Schema Ref */
            schema_ref: string;
        };
        /**
         * StagedCapability
         * @description A to-be-registered ``kind: mcp`` capability inferred from one MCP tool.
         *
         *     ``input_artifact_key`` / ``output_artifact_key`` reference two ``StagedArtifact``s
         *     by key (same session).
         */
        StagedCapability: {
            /** Capability Id */
            capability_id: string;
            /** Description */
            description?: string | null;
            /** Endpoint */
            endpoint: string;
            /** Headers */
            headers?: {
                [key: string]: string;
            };
            /** Idempotent */
            idempotent?: boolean | null;
            /** Input Artifact Key */
            input_artifact_key: string;
            /** Input Name */
            input_name: string;
            /** Min Hitl Mode */
            min_hitl_mode?: string | null;
            /** Output Artifact Key */
            output_artifact_key: string;
            /** Output Name */
            output_name: string;
            /**
             * Side Effect
             * @default read_only
             */
            side_effect: string;
            /** Source Tool */
            source_tool?: string | null;
            /** Title */
            title: string;
            /** Tool */
            tool: string;
            /**
             * Transport
             * @default streamable_http
             */
            transport: string;
            /** Version */
            version: string;
        };
        /** StagedGatewayVariable */
        StagedGatewayVariable: {
            /** Gateway Id */
            gateway_id: string;
            /** Source Artifact */
            source_artifact: string;
            /** Variable */
            variable: string;
        };
        /** StagedSod */
        StagedSod: {
            /** Elements */
            elements?: string[];
        };
        /** StagedTriageRule */
        StagedTriageRule: {
            /** Description */
            description?: string | null;
            /**
             * Priority
             * @default 100
             */
            priority: number;
            /** Rule Id */
            rule_id: string;
            /** When */
            when: {
                [key: string]: unknown;
            };
        };
        /**
         * SubProcessSummary
         * @description ADR-032 Phase 2.6: an embedded sub-process for the coverage overlay + bindings grouping.
         */
        SubProcessSummary: {
            /** Id */
            id: string;
            /** Member Ids */
            member_ids?: string[];
            /** Name */
            name?: string | null;
        };
        /** ToolCompliance */
        ToolCompliance: {
            /** Compliant */
            compliant: boolean;
            /** Reasons */
            reasons?: string[];
        };
        /** TriageRule */
        "TriageRule-Input": {
            /** Description */
            description?: string | null;
            /**
             * Priority
             * @description Lower number wins when multiple packs match
             */
            priority: number;
            /** Rule Id */
            rule_id: string;
            /** When */
            when: components["schemas"]["AllPredicate-Input"] | components["schemas"]["AnyPredicate-Input"] | components["schemas"]["NotPredicate-Input"] | components["schemas"]["LeafPredicate"];
        };
        /** TriageRule */
        "TriageRule-Output": {
            /** Description */
            description?: string | null;
            /**
             * Priority
             * @description Lower number wins when multiple packs match
             */
            priority: number;
            /** Rule Id */
            rule_id: string;
            /** When */
            when: components["schemas"]["AllPredicate-Output"] | components["schemas"]["AnyPredicate-Output"] | components["schemas"]["NotPredicate-Output"] | components["schemas"]["LeafPredicate"];
        };
        /** ValidationError */
        ValidationError: {
            /** Context */
            ctx?: Record<string, never>;
            /** Input */
            input?: unknown;
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
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
    introspect_mcp_capabilities_introspect_mcp_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IntrospectMcpRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["IntrospectMcpResponse"];
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
    list_sessions_onboarding_get: {
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
                    "application/json": components["schemas"]["OnboardingSession"][];
                };
            };
        };
    };
    create_session_onboarding_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateSessionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingSession"];
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
    get_session_onboarding__session_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["OnboardingSession"];
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
    delete_session_onboarding__session_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
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
    assemble_onboarding__session_id__assemble_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["OnboardingSession"];
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
    set_bindings_onboarding__session_id__bindings_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetBindingsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingSession"];
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
    attach_bpmn_onboarding__session_id__bpmn_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttachBpmnRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingSession"];
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
    set_capabilities_onboarding__session_id__capabilities_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetCapabilitiesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingSession"];
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
    commit_onboarding__session_id__commit_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
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
                    "application/json": components["schemas"]["OnboardingSession"];
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
    set_policies_onboarding__session_id__policies_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetPoliciesRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingSession"];
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
    set_triage_onboarding__session_id__triage_put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetTriageRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OnboardingSession"];
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
    list_roles_roles_get: {
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
                    "application/json": components["schemas"]["RoleInUse"][];
                };
            };
        };
    };
}
