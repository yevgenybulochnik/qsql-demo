-- Demo data for demo.qsql, loaded into the compose Postgres's `quicksql` database:
--   docker compose up -d --wait
--   docker compose exec -T postgres psql -U quicksql -d quicksql -q < demo/seed.sql
DROP TABLE IF EXISTS orders, customers;

CREATE TABLE customers (
  customer_id int PRIMARY KEY,
  name        text,
  region      text,
  tier        text
);
INSERT INTO customers VALUES
  (1,'Ada Lovelace','EMEA','gold'), (2,'Grace Hopper','AMER','gold'),
  (3,'Alan Turing','EMEA','silver'), (4,'Katherine Johnson','AMER','silver'),
  (5,'Radia Perlman','APAC','bronze'), (6,'Barbara Liskov','AMER','gold'),
  (7,'Margaret Hamilton','EMEA','bronze'), (8,'Shafi Goldwasser','APAC','silver');

CREATE TABLE orders (
  order_id    int PRIMARY KEY,
  customer_id int REFERENCES customers,
  placed_at   date,
  status      text,
  amount      numeric(10,2)
);
INSERT INTO orders
SELECT g,
       1 + (g * 7) % 8,
       DATE '2026-01-01' + ((g * 13) % 180),
       (ARRAY['shipped','pending','refunded','shipped','shipped'])[1 + (g % 5)],
       round((25 + (g * 37) % 900)::numeric, 2)
FROM generate_series(1, 5000) g;
