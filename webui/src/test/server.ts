import { setupServer } from "msw/node";

/**
 * MSW server for component tests only (MSW is a devDependency and never ships in
 * the app bundle). Tests register their own per-test handlers via `server.use(...)`
 * with small, obviously-synthetic values — see src/test/fixtures.ts. There are no
 * default handlers, so an un-stubbed request is a visible test failure.
 */
export const server = setupServer();
