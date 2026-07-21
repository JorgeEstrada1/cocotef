/* Configuración de la App de Producción (frontend en Vercel).
 *
 * URL base de la API (backend Flask en PythonAnywhere). Puedes cambiarla aquí,
 * o inyectar `window.API_BASE_URL` antes de que cargue este script (por ejemplo
 * desde una variable de entorno de Vercel usando un build step).
 *
 * Si el backend define la variable de entorno MOBILE_API_KEY, pon aquí la misma
 * clave en API_KEY para autenticar las peticiones.
 */
window.APP_CONFIG = {
  API_BASE_URL: (window.API_BASE_URL || "https://cocoteff.pythonanywhere.com").replace(/\/+$/, ""),
  API_KEY: window.API_KEY || "",
};
