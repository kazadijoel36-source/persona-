// Single place to point the frontend at your backend.
// Change this once you deploy the API somewhere other than localhost.
// NOTE: this used to also be redeclared inside js/api.js's IIFE, which
// silently shadowed this file — anyone updating only this file to point
// at a new backend would have seen no effect. api.js now reads
// window.API_BASE instead of declaring its own copy.
window.API_BASE = "https://persona-8xev.onrender.com";
