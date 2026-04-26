-- B1: link tenants to Clerk identity so /tenants/me can resolve the
-- requester's tenant from the JWT (sub or org_id) instead of hardcoded id=1.
-- Both columns nullable: existing rows continue to work; backfill via
-- scripts/link_tenant_clerk_identity.py once the user picks ids.

ALTER TABLE tenants ADD COLUMN clerk_user_id TEXT;
ALTER TABLE tenants ADD COLUMN clerk_org_id TEXT;

-- Partial unique indexes — at most one tenant per Clerk user/org, but multiple
-- tenants without Clerk linkage (legacy / CLI-only) are allowed.
CREATE UNIQUE INDEX IF NOT EXISTS tenants_clerk_user_idx
    ON tenants(clerk_user_id) WHERE clerk_user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS tenants_clerk_org_idx
    ON tenants(clerk_org_id) WHERE clerk_org_id IS NOT NULL;
