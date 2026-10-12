# Redshift sample DDL — migration test input

DDL only, **no data**. Extracted live from the Redshift cluster on `2026-10-12T17:26:51+00:00`.

> **Copy:** every block below is a fenced `sql` block — GitHub and VS Code's Markdown preview
> show a copy button on hover. For one-click copy per object / schema / everything, open
> [`redshift-ddl.html`](redshift-ddl.html).

## Summary

| Schema | Purpose | Tables | Functions | Procedures |
|---|---|---:|---:|---:|
| `demo_fast_test` | Lakebridge demo — tables, 5 UDFs and a stored procedure | 5 | 5 | 1 |
| `demo_schema_test` | Lakebridge demo — whole-schema batch test | 2 | 0 | 0 |
| `public` | AWS TICKIT sample dataset | 7 | 0 | 0 |

**Total:** 20 objects — 14 table(s), 5 function(s), 1 procedure(s)

## What a migration has to translate

Redshift-only constructs present in this DDL. Databricks has no equivalent for most of them, so
each is a test of how the migration handles it:

| Construct | Where | Databricks |
|---|---|---|
| `ENCODE az64` / `raw` / `lzo` | every TICKIT + demo column | dropped — Delta compresses itself |
| `DISTKEY` / `DISTSTYLE KEY` / `ALL` | TICKIT tables | dropped — no distribution model |
| `SORTKEY` | TICKIT tables | `CLUSTER BY` / liquid clustering, or dropped |
| SQL UDF with `$$` body + volatility | 5 `demo_fast_test` functions | `CREATE FUNCTION ... RETURN` |
| PL/pgSQL stored procedure | `sp_top_customers` | rewrite — SQL scripting or a notebook |

Excluded on purpose: `pg_auto_copy.copy_job_detail` — a Redshift system view for the
auto-copy feature, not sample data.

---

## `demo_fast_test`

Lakebridge demo — tables, 5 UDFs and a stored procedure

```sql
CREATE SCHEMA IF NOT EXISTS demo_fast_test;
```

### `demo_fast_test.customers`

_table · 3 columns_ · `ENCODE`

```sql
CREATE TABLE demo_fast_test.customers (
    id integer NOT NULL ENCODE az64,
    name character varying(50) ENCODE lzo COLLATE case_sensitive,
    signup_year integer ENCODE az64
)
DISTSTYLE AUTO;
```

### `demo_fast_test.orders`

_table · 3 columns_ · `ENCODE`

```sql
CREATE TABLE demo_fast_test.orders (
    id integer NOT NULL ENCODE az64,
    customer_id integer ENCODE az64,
    amount integer ENCODE az64
)
DISTSTYLE AUTO;
```

### `demo_fast_test.payments`

_table · 5 columns_ · `ENCODE`

```sql
CREATE TABLE demo_fast_test.payments (
    payment_id integer NOT NULL ENCODE az64,
    order_id integer NOT NULL ENCODE az64,
    amount numeric(10,2) NOT NULL ENCODE az64,
    paid_on date NOT NULL ENCODE az64,
    payment_method character varying(20) NOT NULL ENCODE lzo COLLATE case_sensitive
)
DISTSTYLE AUTO;
```

### `demo_fast_test.products`

_table · 5 columns_ · `ENCODE`

```sql
CREATE TABLE demo_fast_test.products (
    product_id integer NOT NULL ENCODE az64,
    sku character varying(20) NOT NULL ENCODE lzo COLLATE case_sensitive,
    product_name character varying(60) NOT NULL ENCODE lzo COLLATE case_sensitive,
    unit_price numeric(10,2) NOT NULL ENCODE az64,
    in_stock boolean NOT NULL ENCODE raw
)
DISTSTYLE AUTO;
```

### `demo_fast_test.regions`

_table · 3 columns_ · `ENCODE`

```sql
CREATE TABLE demo_fast_test.regions (
    region_id integer NOT NULL ENCODE az64,
    region_name character varying(40) NOT NULL ENCODE lzo COLLATE case_sensitive,
    country character varying(40) NOT NULL ENCODE lzo COLLATE case_sensitive
)
DISTSTYLE AUTO;
```

### `demo_fast_test.f_customer_tenure`

_function_ · `SQL UDF`, `$$ body`

```sql
CREATE OR REPLACE FUNCTION demo_fast_test.f_customer_tenure(signup_year integer)
RETURNS integer
STABLE
AS $$ SELECT CAST(DATE_PART(year, CURRENT_DATE) - $1 AS INTEGER) $$
LANGUAGE sql;
```

### `demo_fast_test.f_discounted_total`

_function_ · `SQL UDF`, `$$ body`

```sql
CREATE OR REPLACE FUNCTION demo_fast_test.f_discounted_total(amount double precision, pct double precision)
RETURNS double precision
STABLE
AS $$ SELECT $1 * (1 - $2 / 100.0) $$
LANGUAGE sql;
```

### `demo_fast_test.f_is_active`

_function_ · `SQL UDF`, `$$ body`

```sql
CREATE OR REPLACE FUNCTION demo_fast_test.f_is_active(signup_year integer)
RETURNS boolean
STABLE
AS $$ SELECT $1 >= 2022 $$
LANGUAGE sql;
```

### `demo_fast_test.f_revenue_score`

_function_ · `SQL UDF`, `$$ body`

```sql
CREATE OR REPLACE FUNCTION demo_fast_test.f_revenue_score(amount double precision)
RETURNS integer
STABLE
AS $$ SELECT CASE WHEN $1 < 1000 THEN 1 WHEN $1 < 100000 THEN 2 ELSE 3 END $$
LANGUAGE sql;
```

### `demo_fast_test.f_tenure_years`

_function_ · `SQL UDF`, `$$ body`

```sql
CREATE OR REPLACE FUNCTION demo_fast_test.f_tenure_years(signup_year integer)
RETURNS integer
STABLE
AS $$ SELECT 2026 - $1 $$
LANGUAGE sql;
```

### `demo_fast_test.sp_top_customers`

_procedure_ · `PL/pgSQL`, `$$ body`

```sql
CREATE OR REPLACE PROCEDURE demo_fast_test.sp_top_customers(min_spend double precision)
 LANGUAGE plpgsql
AS $$
BEGIN
    DROP TABLE IF EXISTS demo_fast_test.top_customers;
    CREATE TABLE demo_fast_test.top_customers AS
    SELECT c.id            AS customer_id,
           c.name          AS customer_name,
           c.signup_year   AS signup_year,
           COUNT(o.id)     AS order_count,
           SUM(o.amount)   AS total_spend
    FROM demo_fast_test.customers c
    JOIN demo_fast_test.orders o ON o.customer_id = c.id
    GROUP BY c.id, c.name, c.signup_year
    HAVING SUM(o.amount) >= min_spend;
END;
$$;
```

---

## `demo_schema_test`

Lakebridge demo — whole-schema batch test

```sql
CREATE SCHEMA IF NOT EXISTS demo_schema_test;
```

### `demo_schema_test.departments`

_table · 3 columns_ · `ENCODE`

```sql
CREATE TABLE demo_schema_test.departments (
    department_id integer NOT NULL ENCODE az64,
    department_name character varying(40) NOT NULL ENCODE lzo COLLATE case_sensitive,
    location character varying(40) NOT NULL ENCODE lzo COLLATE case_sensitive
)
DISTSTYLE AUTO;
```

### `demo_schema_test.employees`

_table · 5 columns_ · `ENCODE`

```sql
CREATE TABLE demo_schema_test.employees (
    employee_id integer NOT NULL ENCODE az64,
    full_name character varying(60) NOT NULL ENCODE lzo COLLATE case_sensitive,
    department_id integer NOT NULL ENCODE az64,
    hired_on date NOT NULL ENCODE az64,
    salary numeric(10,2) NOT NULL ENCODE az64
)
DISTSTYLE AUTO;
```

---

## `public`

AWS TICKIT sample dataset

```sql
CREATE SCHEMA IF NOT EXISTS public;
```

### `public.category`

_table · 4 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.category (
    catid smallint NOT NULL ENCODE raw distkey,
    catgroup character varying(10) ENCODE lzo COLLATE case_sensitive,
    catname character varying(10) ENCODE lzo COLLATE case_sensitive,
    catdesc character varying(50) ENCODE lzo COLLATE case_sensitive
)
DISTSTYLE KEY
SORTKEY ( catid );
```

### `public.date`

_table · 8 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.date (
    dateid smallint NOT NULL ENCODE raw distkey,
    caldate date NOT NULL ENCODE az64,
    day character(3) NOT NULL ENCODE lzo COLLATE case_sensitive,
    week smallint NOT NULL ENCODE az64,
    month character(5) NOT NULL ENCODE lzo COLLATE case_sensitive,
    qtr character(5) NOT NULL ENCODE lzo COLLATE case_sensitive,
    year smallint NOT NULL ENCODE az64,
    holiday boolean DEFAULT false ENCODE raw
)
DISTSTYLE KEY
SORTKEY ( dateid );
```

### `public.event`

_table · 6 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.event (
    eventid integer NOT NULL ENCODE az64 distkey,
    venueid smallint NOT NULL ENCODE az64,
    catid smallint NOT NULL ENCODE az64,
    dateid smallint NOT NULL ENCODE raw,
    eventname character varying(200) ENCODE lzo COLLATE case_sensitive,
    starttime timestamp without time zone ENCODE az64
)
DISTSTYLE KEY
SORTKEY ( dateid );
```

### `public.listing`

_table · 8 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.listing (
    listid integer NOT NULL ENCODE az64 distkey,
    sellerid integer NOT NULL ENCODE az64,
    eventid integer NOT NULL ENCODE az64,
    dateid smallint NOT NULL ENCODE raw,
    numtickets smallint NOT NULL ENCODE az64,
    priceperticket numeric(8,2) ENCODE az64,
    totalprice numeric(8,2) ENCODE az64,
    listtime timestamp without time zone ENCODE az64
)
DISTSTYLE KEY
SORTKEY ( dateid );
```

### `public.sales`

_table · 10 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.sales (
    salesid integer NOT NULL ENCODE az64,
    listid integer NOT NULL ENCODE az64 distkey,
    sellerid integer NOT NULL ENCODE az64,
    buyerid integer NOT NULL ENCODE az64,
    eventid integer NOT NULL ENCODE az64,
    dateid smallint NOT NULL ENCODE raw,
    qtysold smallint NOT NULL ENCODE az64,
    pricepaid numeric(8,2) ENCODE az64,
    commission numeric(8,2) ENCODE az64,
    saletime timestamp without time zone ENCODE az64
)
DISTSTYLE KEY
SORTKEY ( dateid );
```

### `public.users`

_table · 18 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.users (
    userid integer NOT NULL ENCODE raw distkey,
    username character(8) ENCODE lzo COLLATE case_sensitive,
    firstname character varying(30) ENCODE lzo COLLATE case_sensitive,
    lastname character varying(30) ENCODE lzo COLLATE case_sensitive,
    city character varying(30) ENCODE lzo COLLATE case_sensitive,
    state character(2) ENCODE lzo COLLATE case_sensitive,
    email character varying(100) ENCODE lzo COLLATE case_sensitive,
    phone character(14) ENCODE lzo COLLATE case_sensitive,
    likesports boolean ENCODE raw,
    liketheatre boolean ENCODE raw,
    likeconcerts boolean ENCODE raw,
    likejazz boolean ENCODE raw,
    likeclassical boolean ENCODE raw,
    likeopera boolean ENCODE raw,
    likerock boolean ENCODE raw,
    likevegas boolean ENCODE raw,
    likebroadway boolean ENCODE raw,
    likemusicals boolean ENCODE raw
)
DISTSTYLE KEY
SORTKEY ( userid );
```

### `public.venue`

_table · 5 columns_ · `ENCODE`, `DISTKEY`, `SORTKEY`

```sql
CREATE TABLE public.venue (
    venueid smallint NOT NULL ENCODE raw distkey,
    venuename character varying(100) ENCODE lzo COLLATE case_sensitive,
    venuecity character varying(30) ENCODE lzo COLLATE case_sensitive,
    venuestate character(2) ENCODE lzo COLLATE case_sensitive,
    venueseats integer ENCODE az64
)
DISTSTYLE KEY
SORTKEY ( venueid );
```

---

## Regenerate

```bash
backend/.venv/bin/python scripts/extract_redshift_ddl.py
```

```bash
python3 scripts/build_redshift_ddl_docs.py
```
