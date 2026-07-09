// GENERATED — DO NOT HAND-EDIT.
// Run `pnpm gen:api` to regenerate the stub types from its live OpenAPI document.
// `pnpm gen:api:check` fails when this file drifts from the running API.

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
    "/exceptions/generate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Generate */
        post: operations["generate_exceptions_generate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/exceptions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Exceptions */
        get: operations["list_exceptions_exceptions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/exceptions/{exception_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Exception */
        get: operations["get_exception_exceptions__exception_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/exceptions/{exception_id}/attachments/{attachment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Attachment */
        get: operations["get_attachment_exceptions__exception_id__attachments__attachment_id__get"];
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
        /** Account */
        Account: {
            /** Id */
            id: string;
            /** Scheme */
            scheme: string;
        };
        /** Agent */
        Agent: {
            /** Bic */
            bic: string;
        };
        /** Attachment */
        Attachment: {
            /** Attachment Id */
            attachment_id: string;
            /** Name */
            name: string;
            /** Media Type */
            media_type: string;
            /** Sha256 */
            sha256: string;
            /** Fetch Url */
            fetch_url: string;
        };
        /**
         * GenerateRequest
         * @description Body for ``POST /exceptions/generate`` — every field is optional.
         *
         *     Anything the caller pins is honored; the rest is randomized per exception.
         */
        GenerateRequest: {
            /** Tenant */
            tenant?: string | null;
            /** Reason Code */
            reason_code?: ("AC01" | "AC04" | "RC01" | "BE04") | null;
            /** Amount */
            amount?: number | null;
            /** Currency */
            currency?: string | null;
            /** Include Attachments */
            include_attachments?: boolean | null;
            /**
             * Count
             * @default 1
             */
            count: number;
        };
        /** GenerateResponse */
        GenerateResponse: {
            /** Created */
            created: components["schemas"]["GeneratedItem"][];
        };
        /**
         * GeneratedItem
         * @description One generated exception plus how it was published.
         */
        GeneratedItem: {
            exception: components["schemas"]["StoredException"];
            /** Routing Key */
            routing_key: string;
            /** Published */
            published: boolean;
            /** Warning */
            warning?: string | null;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** MonetaryAmount */
        MonetaryAmount: {
            /** Currency */
            currency: string;
            /** Value */
            value: number;
        };
        /** Party */
        Party: {
            /** Name */
            name: string;
            account?: components["schemas"]["Account"] | null;
        };
        /**
         * PaymentDetails
         * @description pacs.008-shaped payment block.
         */
        PaymentDetails: {
            /** Msg Type */
            msg_type: string;
            /** Uetr */
            uetr: string;
            /** Instruction Id */
            instruction_id: string;
            /** End To End Id */
            end_to_end_id: string;
            settlement_amount: components["schemas"]["MonetaryAmount"];
            /** Value Date */
            value_date: string;
            debtor: components["schemas"]["Party"];
            debtor_agent: components["schemas"]["Agent"];
            creditor: components["schemas"]["Party"];
            creditor_agent: components["schemas"]["Agent"];
            /** Charges */
            charges: string;
        };
        /** RelatedMessage */
        RelatedMessage: {
            /** Type */
            type: string;
            /** Id */
            id: string;
            /** Assigner Bic */
            assigner_bic: string;
        };
        /** Source */
        Source: {
            /** System */
            system: string;
            /** Channel */
            channel: string;
        };
        /**
         * StoredException
         * @description Envelope wrapped with store-managed metadata (as persisted in Mongo).
         */
        StoredException: {
            /** Exception Id */
            exception_id: string;
            /** Tenant */
            tenant: string;
            source: components["schemas"]["Source"];
            /** Received At */
            received_at: string;
            /** Exception Type */
            exception_type: string;
            /** Reason Codes */
            reason_codes: string[];
            /** Reason Narrative */
            reason_narrative: string;
            /** Status */
            status: string;
            payment: components["schemas"]["PaymentDetails"];
            /** Related Messages */
            related_messages?: components["schemas"]["RelatedMessage"][];
            /** Attachments */
            attachments?: components["schemas"]["Attachment"][];
            /**
             * Schema Version
             * @default pin.payments.wire_exception/1.0
             */
            schema_version: string;
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
    generate_exceptions_generate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["GenerateRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GenerateResponse"];
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
    list_exceptions_exceptions_get: {
        parameters: {
            query?: {
                tenant?: string | null;
                exception_type?: string | null;
                status?: string | null;
                reason_code?: string | null;
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
                    "application/json": components["schemas"]["StoredException"][];
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
    get_exception_exceptions__exception_id__get: {
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
                    "application/json": components["schemas"]["StoredException"];
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
    get_attachment_exceptions__exception_id__attachments__attachment_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                exception_id: string;
                attachment_id: string;
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
}
