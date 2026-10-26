-- One intact product's physical token cards, using the deck Token cards syntax.
-- Blank means no packing record; existing products retain their legacy warnings.
alter table product_status add column token_cards text not null default '';
