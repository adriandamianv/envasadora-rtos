# Subir la simulación a wokwi.com (proyecto web)

Wokwi no tiene API para crear proyectos: se hace una vez a mano (~2 min).

1. Entra a https://wokwi.com con tu cuenta y elige
   **+ New Project → ESP32 → Arduino**.
2. En la pestaña `sketch.ino`: borra el contenido y pega el de
   `wokwi-web/sketch.ino`.
3. En la pestaña `diagram.json`: reemplaza el contenido con el de
   `wokwi-web/diagram.json`.
4. En la pestaña `libraries.txt` (créala con el + si no existe): pega el
   contenido de `wokwi-web/libraries.txt`.
5. Pulsa ▶. El botón verde INICIO de la simulación arranca una orden local;
   desde la web de Render se controla por MQTT (iniciar/pausar/reanudar).
6. Para compartirlo: **Save** → botón **Share** → copia el enlace público
   (queda tipo https://wokwi.com/projects/XXXXXXXXXXXX).

Sugerencia: pega ese enlace en el README del repo y en el informe.
