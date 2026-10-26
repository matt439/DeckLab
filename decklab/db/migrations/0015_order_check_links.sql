-- Optional proof for explicitly authored arrival-check row targets. Legacy
-- checks and verified history remain ordered text arrays and stay unscoped.
alter table order_component add column check_links jsonb null;
