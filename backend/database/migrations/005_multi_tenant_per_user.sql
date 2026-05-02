-- Browser-driven onboarding: a single Clerk user can connect repos from
-- multiple GitHub accounts/orgs (e.g., personal + work). Each GitHub App
-- installation still maps to exactly one tenant (UNIQUE on
-- github_installation_id stays), but a Clerk user can own multiple tenants.
--
-- This migration drops the partial-unique indexes from 004 and replaces them
-- with non-unique lookup indexes. /tenants/mine returns a list now.

DROP INDEX IF EXISTS tenants_clerk_user_idx;
DROP INDEX IF EXISTS tenants_clerk_org_idx;

CREATE INDEX IF NOT EXISTS idx_tenants_clerk_user_id
    ON tenants(clerk_user_id) WHERE clerk_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tenants_clerk_org_id
    ON tenants(clerk_org_id) WHERE clerk_org_id IS NOT NULL;
