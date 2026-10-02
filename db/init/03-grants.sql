-- Least privilege for the Toolbox login: read users and orders, append to actions_log.
-- No UPDATE or DELETE on any table, so even a mutating tool declared by mistake fails here (backs up M-6).
GRANT CONNECT ON DATABASE shop TO toolbox;
GRANT USAGE ON SCHEMA public TO toolbox;
GRANT SELECT ON users, customer_orders TO toolbox;
GRANT INSERT ON actions_log TO toolbox;
GRANT USAGE ON SEQUENCE actions_log_id_seq TO toolbox;
