import os
import requests
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import google.generativeai as genai
import json
from functools import lru_cache
import time

app = Flask(__name__)

# --- CONFIGURACIÓN DE GEMINI ---
API_KEY = os.environ.get("API_KEY_GEMINI")
if API_KEY:
    genai.configure(api_key=API_KEY)
else:
    print("ADVERTENCIA: API_KEY_GEMINI no configurada")

# Cache para evitar consultas repetidas
@lru_cache(maxsize=100)
def analizar_con_gemini(marca, descripcion):
    """Análisis de viabilidad con Gemini AI"""
    if not API_KEY:
        return {
            "viabilidad": 50,
            "clases": ["Configuración pendiente"],
            "nota": "API Key de Gemini no configurada.",
            "recomendaciones": ["Configurar API_KEY_GEMINI"]
        }
    
    try:
        # IMPORTANTE: No incluir "models/" en el nombre
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""Analiza la marca '{marca}' para el giro '{descripcion}' en México.

Responde ÚNICAMENTE con JSON válido (sin markdown):
{{
  "viabilidad": 75,
  "clases": ["Clase 35: Servicios comerciales", "Clase 42: Servicios tecnológicos"],
  "nota": "Análisis de viabilidad",
  "recomendaciones": ["Consultar especialista", "Verificar clases específicas"]
}}"""
        
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.7,
                max_output_tokens=1024,
            )
        )
        
        text = response.text.strip()
        
        # Limpiar markdown
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                if '{' in part and '}' in part:
                    text = part.replace("json", "").strip()
                    break
        
        return json.loads(text)
        
    except Exception as e:
        print(f"Error en Gemini: {e}")
        return {
            "viabilidad": 50,
            "clases": ["Consulta manual requerida"],
            "nota": "Error en análisis automático. Verifica con especialista.",
            "recomendaciones": ["Consultar con abogado especializado"]
        }
    except Exception as e:
        print(f"Error en Gemini: {e}")
        return {
            "viabilidad": 40,
            "clases": ["Consulta manual requerida"],
            "nota": "No se pudo completar el análisis automático por error técnico.",
            "recomendaciones": ["Consultar con un abogado especializado en propiedad industrial"]
        }

def buscar_en_marcanet_http(marca):
    """
    Búsqueda usando requests en lugar de Selenium
    Más rápido, ligero y confiable
    """
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-MX,es;q=0.9',
        'Referer': 'https://acervomarcas.impi.gob.mx:8181/marcanet/'
    })
    
    try:
        # 1. Obtener la página de búsqueda para cookies/sesión
        url_base = "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/datos/bsqDenominacionCompleto.pgi"
        response = session.get(url_base, timeout=15)
        
        if response.status_code != 200:
            return "ERROR_CONEXION"
        
        # 2. Preparar datos del formulario
        # Nota: Estos nombres pueden cambiar, habría que inspeccionar el HTML real
        data = {
            'denominacion': marca,
            'tipo_busqueda': 'EXACTA',  # o 'FONÉTICA' según necesites
            'vigentes': 'true'
        }
        
        # 3. Enviar búsqueda (método POST)
        url_busqueda = "https://acervomarcas.impi.gob.mx:8181/marcanet/controlers/ctBusqueda.php"
        response = session.post(url_busqueda, data=data, timeout=20)
        
        # 4. Analizar resultados
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Buscar indicadores de resultados
        no_resultados = [
            "No se encontraron registros",
            "sin resultados",
            "0 resultados"
        ]
        
        texto_respuesta = response.text.lower()
        
        if any(msg.lower() in texto_respuesta for msg in no_resultados):
            return "DISPONIBLE"
        
        # Si hay tabla de resultados o registros
        if soup.find('table') or 'expediente' in texto_respuesta:
            return "OCUPADA"
        
        # Si no estamos seguros
        return "VERIFICAR_MANUAL"
        
    except requests.Timeout:
        print("Timeout al consultar IMPI")
        return "ERROR_TIMEOUT"
    except requests.RequestException as e:
        print(f"Error de conexión: {e}")
        return "ERROR_CONEXION"
    except Exception as e:
        print(f"Error inesperado: {e}")
        return "ERROR_DESCONOCIDO"

def buscar_marca_fallback(marca):
    """
    Método alternativo: Buscar en el buscador público simplificado
    """
    try:
        # URL alternativa del IMPI (puede variar)
        url = f"https://siga.impi.gob.mx/newSIGA/content/common/principal.jsf"
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Aquí irían las peticiones específicas según la estructura del sitio
        # Por ahora retornamos que requiere verificación manual
        return "VERIFICAR_MANUAL"
        
    except Exception as e:
        print(f"Error en fallback: {e}")
        return "ERROR_CONEXION"

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/consultar', methods=['POST'])
def consultar():
    data = request.json
    marca = data.get('marca', '').strip()
    desc = data.get('descripcion', '').strip()
    
    if not marca or not desc:
        return jsonify({
            "error": "Marca y descripción son obligatorias"
        }), 400
    
    # Normalizar marca
    marca = marca.upper()
    
    # 1. Análisis con IA (rápido)
    resultado = analizar_con_gemini(marca, desc)
    
    # 2. Búsqueda en IMPI (más lento)
    disponibilidad = buscar_en_marcanet_http(marca)
    
    # Si falla el método principal, intentar fallback
    if disponibilidad.startswith("ERROR"):
        time.sleep(2)
        disponibilidad = buscar_marca_fallback(marca)
    
    # 3. Lógica de cruce
    resultado['status_impi'] = disponibilidad
    
    if disponibilidad == "OCUPADA":
        resultado['viabilidad'] = 5
        resultado['nota'] = "⚠️ ALERTA CRÍTICA: Esta marca ya está registrada en el IMPI. Su uso podría resultar en infracciones legales."
        resultado['recomendaciones'] = [
            "Considerar una variación de la marca",
            "Consultar con un abogado especializado en propiedad industrial",
            "Verificar si la marca está vigente o abandonada"
        ]
    elif disponibilidad == "DISPONIBLE":
        resultado['nota'] = f"✅ Marca aparentemente disponible. {resultado.get('nota', '')}"
    elif disponibilidad == "VERIFICAR_MANUAL":
        resultado['viabilidad'] = max(resultado.get('viabilidad', 50) - 20, 20)
        resultado['nota'] = "⚠️ Se requiere verificación manual en el IMPI. El sistema automático no pudo confirmar disponibilidad."
    else:  # ERROR_*
        resultado['viabilidad'] = 50
        resultado['nota'] = "⚠️ No se pudo verificar en el IMPI por problemas técnicos. Se recomienda consulta manual."
    
    return jsonify(resultado)

@app.route('/health')
def health():
    """Endpoint para verificar que el servicio está vivo"""
    return jsonify({"status": "ok", "service": "marca-checker"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
