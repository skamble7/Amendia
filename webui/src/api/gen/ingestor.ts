// GENERATED — DO NOT HAND-EDIT.
// Run `npm run gen:api` to regenerate the ingestor types from its live OpenAPI document.
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
    "/ingestions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Ingestions */
        get: operations["list_ingestions_ingestions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/ingestions/{exception_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Ingestion */
        get: operations["get_ingestion_ingestions__exception_id__get"];
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
        /**
         * EventRef
         * @description The thin event that triggered this ingestion (kept for audit).
         */
        EventRef: {
            /** Event Id */
            event_id: string;
            /**
             * Occurred At
             * Format: date-time
             */
            occurred_at: string;
            /** Schema Version */
            schema_version: string;
            /** Routing Key */
            routing_key: string;
            /** Fetch Url */
            fetch_url: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** IngestionRecord */
        IngestionRecord: {
            /** Exception Id */
            exception_id: string;
            /** Tenant */
            tenant: string;
            /** Exception Type */
            exception_type: string;
            event: components["schemas"]["EventRef"];
            /** Exception Detail */
            exception_detail?: {
                [key: string]: unknown;
            } | null;
            /** Fetch Error */
            fetch_error?: string | null;
            /** @default received */
            status: components["schemas"]["IngestionStatus"];
            /** Status History */
            status_history?: components["schemas"]["StatusChange"][];
            resolution?: components["schemas"]["ResolutionRef"] | null;
            /** Process Instance Id */
            process_instance_id?: string | null;
            /** No Match */
            no_match?: {
                [key: string]: unknown;
            } | null;
            rejection?: components["schemas"]["RejectionRef"] | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /**
         * IngestionStatus
         * @enum {string}
         */
        IngestionStatus: "received" | "dispatched" | "accepted" | "rejected" | "no_process";
        /**
         * RejectionRef
         * @description The runtime's dispatch rejection detail.
         */
        RejectionRef: {
            /** Reason */
            reason: string;
            /** Detail */
            detail?: string | null;
        };
        /**
         * ResolutionRef
         * @description The pinned pack the registry resolved this exception to.
         */
        ResolutionRef: {
            /** Pack Key */
            pack_key: string;
            /** Pack Version */
            pack_version: string;
            /** Rule Id */
            rule_id: string;
            /** Resolved At */
            resolved_at?: string | null;
        };
        /** StatusChange */
        StatusChange: {
            status: components["schemas"]["IngestionStatus"];
            /**
             * At
             * Format: date-time
             */
            at: string;
            /** Detail */
            detail?: string | null;
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
    list_ingestions_ingestions_get: {
        parameters: {
            query?: {
                tenant?: string | null;
                exception_type?: string | null;
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
                    "application/json": components["schemas"]["IngestionRecord"][];
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
    get_ingestion_ingestions__exception_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                exception_id: string;
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
                    "application/json": components["schemas"]["IngestionRecord"];
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
