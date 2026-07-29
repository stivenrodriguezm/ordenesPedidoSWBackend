const sqlite3 = require('sqlite3').verbose();
const db = new sqlite3.Database('db.sqlite3');

db.all("SELECT id, orden_asociada_id FROM ordenes_pedidotela ORDER BY id DESC LIMIT 5", (err, rows) => {
    if (err) throw err;
    console.log("Pedidos Tela:", rows);
});

db.close();
