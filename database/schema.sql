-- StockLink reference schema for Supabase/Postgres.
-- The FastAPI backend can also create these tables automatically.

create table if not exists stokvels (
    id bigserial primary key,
    name varchar(120) not null,
    monthly_amount numeric(12,2) not null default 500,
    contribution_day int not null default 25 check (contribution_day between 1 and 28),
    created_at timestamptz not null default now()
);

create table if not exists members (
    id bigserial primary key,
    full_name varchar(120) not null,
    phone varchar(30) not null,
    created_at timestamptz not null default now()
);

create table if not exists memberships (
    id bigserial primary key,
    member_id bigint not null references members(id),
    stokvel_id bigint not null references stokvels(id),
    role varchar(20) not null default 'member',
    joined_at date not null default current_date,
    is_active boolean not null default true,
    unique(member_id, stokvel_id)
);

create table if not exists contributions (
    id bigserial primary key,
    member_id bigint not null references members(id),
    stokvel_id bigint not null references stokvels(id),
    amount numeric(12,2) not null check (amount > 0),
    contribution_month varchar(7) not null,
    status varchar(20) not null default 'pending',
    reference varchar(40) not null unique,
    created_at timestamptz not null default now(),
    verified_at timestamptz
);

create table if not exists audit_events (
    id bigserial primary key,
    stokvel_id bigint not null references stokvels(id),
    member_id bigint references members(id),
    event_type varchar(60) not null,
    message text not null,
    created_at timestamptz not null default now()
);

create table if not exists notifications (
    id bigserial primary key,
    member_id bigint not null references members(id),
    title varchar(120) not null,
    body text not null,
    is_read boolean not null default false,
    created_at timestamptz not null default now()
);
