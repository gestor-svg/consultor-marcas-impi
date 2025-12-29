import os
import requests
from flask import Flask, render_template, request, jsonify
from bs4 import BeautifulSoup
import json
from functools import lru_cache
import time

app = Flask(__name__)

# --- CONFIGURACIÓN DE GEMINI ---
API_KEY = os.environ.get("API_KEY_GEMINI")

# Solo importar y configurar si la API key existe
GEMINI_AVAILABLE = False
if API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=API_KEY)
        GEMINI_AVAILABLE = True
        print("✓ Gemini configurado correctamente")
    except Exception as e:
        print(f"⚠ Error configurando Gemini: {e}")
        GEMINI_AVAILABLE = False
else:
    print("⚠ API_KEY_GEMINI no encontrada - funcionando sin IA")

@lru_cache(maxsize=100)
def analizar_con_gemini(marca, descripcion):
    """Análisis de viabilidad con Gemini AI"""
    if not GEMINI_AVAILABLE:
        return {
            "viabilidad": 50,
            "clases": ["IA no disponible - Consulta manual requerida"],
            "nota": "El análisis de IA no está disponible. Verifica la configuración de API Key.",
            "recomendaciones": ["Consultar con un abogado especializado en propiedad industrial"]
        }
    
    try:
        # Probar diferentes modelos en orden de preferencia
        modelos_a_probar = [
            'gemini-2.0-flash',      # Más reciente y rápido
            'gemini-2.5-flash',      # Alternativa reciente
            'gemini-1.5-flash',      # Modelo anterior
            'gemini-pro'             # Fallback clásico
        ]
        
        prompt = f"""Analiza la marca comercial '{marca}' para el giro de negocio '{descripcion}' en México.

Responde ÚNICAMENTE con un objeto JSON válido (sin bloques de código markdown) con exactamente esta estructura:
{{
  "viabilidad": 75,
  "clases": ["Clase 35: Servicios de publicidad y gestión comercial", "Clase 42: Servicios científicos y tecnológicos"],
  "nota": "Análisis de viabilidad de la marca",
  "recomendaciones": ["Verificar disponibilidad en clases específicas", "Consultar con especialista"]
}}

Instrucciones:
- viabilidad: número del 0 al 100
- clases: array con 2-4 clases del Clasificador de Niza relevantes
- nota: texto breve sobre la marca
- recomendaciones: array con 2-4 consejos prácticos"""
        
        ultimo_error = None
        
        for modelo_nombre in modelos_a_probar:
            try:
                print(f"[DEBUG] Intentando modelo: {modelo_nombre}")
                model = genai.GenerativeModel(modelo_nombre)
                
                response = model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.7,
                        max_output_tokens=1024,
                    )
                )
                
                text = response.text.strip()
                print(f"[DEBUG] Respuesta recibida ({len(text)} caracteres)")
                
                # Limpiar markdown si existe
                if "```" in text:
                    parts = text.split("```")
                    for part in parts:
                        if '{' in part and '}' in part:
                            text = part.replace("json", "").replace("JSON", "").strip()
                            break
                
                # Intentar parsear
                resultado = json.loads(text)
                print(f"[DEBUG] ✓ Modelo {modelo_nombre} funcionó correctamente")
                return resultado
                
            except Exception as e:
                ultimo_error = str(e)
                print(f"[DEBUG] ✗ Modelo {modelo_nombre} falló: {e}")
                continue
        
        # Si todos los modelos fallaron
        raise Exception(f"Todos los modelos fallaron. Último error: {ultimo_error}")
        
    except Exception as e:
        print(f"[ERROR] Error en Gemini: {e}")
        return {
            "viabilidad": 50,
            "clases": ["Análisis automático no disponible"],
            "nota": "No se pudo completar el análisis con IA. Se recomienda consulta manual.",
            "recomendaciones": [
                "Consultar con un abogado especializado en propiedad industrial",
                "Verificar manualmente en https://marcanet.impi.gob.mx"
            ]
        }

def buscar_en_marcanet_http(marca):
    """Búsqueda usando requests - Método principal"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-MX,es;q=0.9',
        'Referer': 'https://acervomarcas.impi.gob.mx:8181/marcanet/'
    })
    
    try:
        print(f"[DEBUG] Buscando marca en IMPI: {marca}")
        
        url_base = "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/datos/bsqDenominacionCompleto.pgi"
        response = session.get(url_base, timeout=15)
        
        if response.status_code != 200:
            return "ERROR_CONEXION"
        
        data = {
            'denominacion': marca,
            'tipo_busqueda': 'EXACTA',
            'vigentes': 'true'
        }
        
        url_busqueda = "https://acervomarcas.impi.gob.mx:8181/marcanet/controlers/ctBusqueda.php"
        response = session.post(url_busqueda, data=data, timeout=20)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        no_resultados = [
            "No se encontraron registros",
            "sin resultados",
            "0 resultados",
            "no se encontró"
        ]
        
        texto_respuesta = response.text.lower()
        
        if any(msg.lower() in texto_respuesta for msg in no_resultados):
            print(f"[DEBUG] ✓ Marca DISPONIBLE")
            return "DISPONIBLE"
        
        if soup.find('table') or 'expediente' in texto_respuesta or 'solicitud' in texto_respuesta:
            print(f"[DEBUG] ✗ Marca OCUPADA")
            return "OCUPADA"
        
        print(f"[DEBUG] ? Resultado incierto")
        return "VERIFICAR_MANUAL"
        
    except requests.Timeout:
        print("[ERROR] Timeout al consultar IMPI")
        return "ERROR_TIMEOUT"
    except Exception as e:
        print(f"[ERROR] Error en IMPI: {e}")
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
        return jsonify({"error": "Marca y descripción son obligatorias"}), 400
    
    marca = marca.upper()
    
    print(f"\n{'='*60}")
    print(f"CONSULTA: {marca}")
    print(f"{'='*60}")
    
    # 1. Análisis con IA (o fallback si no está disponible)
    resultado = analizar_con_gemini(marca, desc)
    
    # 2. Búsqueda en IMPI
    disponibilidad = buscar_en_marcanet_http(marca)
    resultado['status_impi'] = disponibilidad
    
    # 3. Ajustar según resultado IMPI
    if disponibilidad == "OCUPADA":
        resultado['viabilidad'] = 5
        resultado['nota'] = f"⚠️ ALERTA CRÍTICA: La marca '{marca}' ya está registrada en el IMPI. Su uso sin autorización podría resultar en infracciones legales."
        resultado['recomendaciones'] = [
            "Elegir un nombre de marca diferente",
            "Verificar si el registro está vigente o abandonado",
            "Consultar si está en clases diferentes a tu giro"
        ]
    elif disponibilidad == "DISPONIBLE":
        resultado['viabilidad'] = max(resultado.get('viabilidad', 70), 80)
        resultado['nota'] = f"✅ Buenas noticias: '{marca}' no aparece registrada. {resultado.get('nota', '')}"
    
    print(f"RESULTADO: Viabilidad={resultado['viabilidad']}%, IMPI={disponibilidad}")
    print(f"{'='*60}\n")
    
    return jsonify(resultado)

@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "gemini": GEMINI_AVAILABLE,
        "version": "3.0"
    })

@app.route('/test-impi/<marca>')
def test_impi(marca):
    """Endpoint de prueba para IMPI"""
    resultado = buscar_en_marcanet_http(marca.upper())
    return jsonify({
        "marca": marca.upper(),
        "status": resultado,
        "timestamp": time.time()
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    print(f"\n{'='*60}")
    print(f"🚀 Consultor de Marcas IMPI v3.0")
    print(f"Puerto: {port}")
    print(f"Gemini: {'✓ Habilitado' if GEMINI_AVAILABLE else '✗ Deshabilitado'}")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=port, debug=False)
