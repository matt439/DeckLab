"""Order Undo audit reads, sharing the backend's active inventory claim when present."""


def latest(store, order_id, product_stems):
    def work(connection):
        return connection.execute("select max(id) from audit.row_change where ("
            "(table_name='purchase_order' and row_key->>'id'=%s) or "
            "(table_name in ('order_component','order_card_item','order_token_item') and row_key->>'order_id'=%s) or "
            "(table_name='product' and row_key->>'stem'=any(%s)) or "
            "(table_name='product_item' and row_key->>'product_stem'=any(%s)) or "
            "(table_name='product_status' and row_key->>'file'=any(%s))) and not "
            "(table_name='product_status' and op='UPDATE' and before is not null and after is not null "
            "and before - array['sleeves','deck_box'] = after - array['sleeves','deck_box'])",
            (order_id, order_id, product_stems, product_stems, [stem + '.csv' for stem in product_stems])).fetchone()[0]
    applying = getattr(store._applying, "connection", None)
    return work(applying) if applying is not None else store._call(work)
