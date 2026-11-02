# -*- coding: utf-8 -*-
# Proyecto Formula E CES Tec - Parte I
# Raspberry Pi Pico W / 2W + 74LS164 + L298N  (MicroPython, Thonny)
#
# Comandos por consola (Tabla 1):
#   pwm  [-4..4]   potencia (negativo = retrocede, 0 = detiene)
#   dir  [-1,0,1,2] -1 izquierda, 0 recto, 1 derecha, 2 retroceder
#   lf   [1,0]     luces frontales
#   lb   [1,0]     luces traseras
#   ll   [1,0]     direccional izquierda
#   lr   [1,0]     direccional derecha
#   ldr  [1,0]     control automatico de luces por fotorresistencia
#   Circle | Infinite | ZigZag | especial
#   stop           (extra) apaga motores
#   luz [1|0]      (extra) lectura del LDR; 'luz 1' monitor continuo, 'luz 0' lo detiene
#   test           (extra) prueba cada motor para verificar cableado

from machine import Pin, PWM, ADC, Timer
import time

# ---------------------------------------------------------------
# PINES  (AJUSTAR a como cableaste tu Figura 8)
# ---------------------------------------------------------------
PIN_DATO = 15      # A y B del 74LS164 (unidos)
PIN_CLK = 14       # CLK del 74LS164
PIN_ENA = 16       # L298N Enable A  (PWM)  -> motor de traccion
PIN_IN1 = 17
PIN_IN2 = 18
PIN_ENB = 19       # L298N Enable B  (PWM)  -> motor de direccion
PIN_IN3 = 20
PIN_IN4 = 21
PIN_LDR = 27       # ADC1

# ---------------------------------------------------------------
# PARAMETROS A CALIBRAR CON TU CARRO
# ---------------------------------------------------------------
FREQ_PWM = 1000
DUTY_MIN = 32000          # ~500 de 1023 en escala de 16 bits (nivel 1)
DUTY_MAX = 65535          # nivel 4
DUTY_GIRO = 50000         # fuerza del motor de direccion
TIEMPO_DIR = 1.5          # s que se mantiene un comando dir
TIEMPO_CIRCULO = 6.0      # s para dar una vuelta completa (calibrar)
TIEMPO_ZIGZAG = 0.8       # s por tramo del zigzag
REPETICIONES_ZIGZAG = 4   # cantidad de zigs
NIVEL_PATRON = 2          # potencia usada en patrones si el carro esta detenido
CONVERSION_VOLTIOS = 3.3 / 65535
V_OSCURO = 1.0            # voltios: por debajo = poca luz -> enciende luces
V_CLARO = 1.3             # voltios: por encima = hay luz -> apaga (histeresis)
LDR_INVERTIDO = False     # True si el voltaje SUBE cuando hay oscuridad
INVERTIR_DIRECCIONALES = True  # True si al ir a la izq. se enciende la der.
INVERTIR_TRACCION = True  # True si "adelante" te movia el carro hacia atras

# ---------------------------------------------------------------
# HARDWARE
# ---------------------------------------------------------------
dato = Pin(PIN_DATO, Pin.OUT, value=0)
clk = Pin(PIN_CLK, Pin.OUT, value=0)

# Los EN van fijos en alto (o con su jumper puesto) y el PWM va en los IN.
# Asi funciona tanto si el modulo trae jumpers en ENA/ENB como si no.
ena = Pin(PIN_ENA, Pin.OUT, value=1)
enb = Pin(PIN_ENB, Pin.OUT, value=1)
in1 = PWM(Pin(PIN_IN1)); in1.freq(FREQ_PWM); in1.duty_u16(0)
in2 = PWM(Pin(PIN_IN2)); in2.freq(FREQ_PWM); in2.duty_u16(0)
in3 = PWM(Pin(PIN_IN3)); in3.freq(FREQ_PWM); in3.duty_u16(0)
in4 = PWM(Pin(PIN_IN4)); in4.freq(FREQ_PWM); in4.duty_u16(0)

ldr_adc = ADC(Pin(PIN_LDR))

# ---------------------------------------------------------------
# ESTADO
# ---------------------------------------------------------------
# Mapa del registro: QA=dir. der, QB=front der, QC=front izq,
#                    QD=tras izq, QE=tras der, QF=dir. izq
luces = {"lr": 0, "lf": 0, "lb": 0, "ll": 0}
modo_ldr = True           # control automatico activo desde el inicio ('ldr 0' lo apaga)
monitor_ldr = False       # True: imprime el voltaje del LDR cada 300 ms
nivel_actual = 0          # -4..4
_en_uso = False           # True mientras se escribe en el 74LS164


# ---------------------------------------------------------------
# LUCES (74LS164)
# ---------------------------------------------------------------
def actualizar_luces():
    """Envia 6 bits al 74LS164. El primer bit enviado termina en QF,
    por eso se envia en orden QF, QE, QD, QC, QB, QA."""
    if INVERTIR_DIRECCIONALES:
        qa = luces["ll"]
        qf = luces["lr"]
    else:
        qa = luces["lr"]
        qf = luces["ll"]
    qb = luces["lf"]
    qc = luces["lf"]
    # las luces traseras tambien se encienden al ir en reversa
    atras = 1 if (luces["lb"] or nivel_actual < 0) else 0
    qd = atras
    qe = atras
    global _en_uso
    _en_uso = True
    for bit in (qf, qe, qd, qc, qb, qa):
        dato.value(bit)
        clk.value(1)
        clk.value(0)
    _en_uso = False


def poner_luz(nombre, valor):
    luces[nombre] = 1 if valor else 0
    actualizar_luces()


def revisar_ldr():
    """Control automatico: oscuro -> enciende los 4 LED; claro -> apaga."""
    if not modo_ldr or _en_uso:
        return
    voltaje = ldr_adc.read_u16() * CONVERSION_VOLTIOS   # mas luz = mas voltaje
    if LDR_INVERTIDO:
        voltaje = 3.3 - voltaje
    if voltaje < V_OSCURO and not luces["lf"]:
        luces["lf"] = 1
        luces["lb"] = 1
        actualizar_luces()
        print("LDR: oscuro ({:.2f} V) -> luces ON".format(voltaje))
    elif voltaje > V_CLARO and luces["lf"]:
        luces["lf"] = 0
        luces["lb"] = 0
        actualizar_luces()
        print("LDR: claro ({:.2f} V) -> luces OFF".format(voltaje))


def esperar(segundos):
    """Espera sin bloquear el control automatico de luces."""
    fin = time.ticks_add(time.ticks_ms(), int(segundos * 1000))
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        revisar_ldr()
        time.sleep_ms(30)


# ---------------------------------------------------------------
# MOTORES (L298N)
# ---------------------------------------------------------------
def duty_nivel(nivel):
    n = abs(nivel)
    if n == 0:
        return 0
    return DUTY_MIN + (n - 1) * (DUTY_MAX - DUTY_MIN) // 3


def _motor(pa, pb, duty, sentido):
    """sentido > 0: PWM en pa; < 0: PWM en pb; 0: ambos apagados."""
    if sentido > 0:
        pb.duty_u16(0)
        pa.duty_u16(duty)
    elif sentido < 0:
        pa.duty_u16(0)
        pb.duty_u16(duty)
    else:
        pa.duty_u16(0)
        pb.duty_u16(0)


def traccion(nivel):
    """nivel -4..4. Positivo adelante, negativo atras."""
    global nivel_actual
    sentido = -nivel if INVERTIR_TRACCION else nivel
    if nivel != 0 and nivel_actual == 0:
        # empujon inicial para vencer la inercia del motor
        _motor(in1, in2, DUTY_MAX, sentido)
        time.sleep_ms(120)
    nivel_actual = nivel
    actualizar_luces()
    _motor(in1, in2, duty_nivel(nivel), sentido)


def direccion(sentido):
    """-1 izquierda, 0 recta (motor apagado), 1 derecha."""
    _motor(in4, in3, DUTY_GIRO, sentido)  # in4 activo = derecha


def detener_todo():
    traccion(0)
    direccion(0)


# ---------------------------------------------------------------
# COMANDOS DE MANDO
# ---------------------------------------------------------------
def cmd_pwm(valor):
    if valor < -4 or valor > 4:
        print("pwm fuera de rango [-4, 4]")
        return
    traccion(valor)
    print("pwm ->", valor)


def cmd_dir(valor):
    if valor not in (-1, 0, 1, 2):
        print("dir fuera de rango [-1, 0, 1, 2]")
        return
    if valor == 0:
        direccion(0)
        print("dir -> recto")
    elif valor == 2:
        # retroceder durante un tiempo visible
        direccion(0)
        nivel = -abs(nivel_actual) if nivel_actual != 0 else -NIVEL_PATRON
        traccion(nivel)
        esperar(TIEMPO_DIR)
        traccion(0)
        print("dir -> retroceder")
    else:
        direccion(valor)
        poner_luz("ll" if valor == -1 else "lr", 1)
        esperar(TIEMPO_DIR)
        direccion(0)
        poner_luz("ll" if valor == -1 else "lr", 0)
        print("dir ->", "izquierda" if valor == -1 else "derecha")


def cmd_luz(nombre, valor):
    if valor not in (0, 1):
        print(nombre, "solo acepta 1 o 0")
        return
    poner_luz(nombre, valor)
    print(nombre, "->", valor)


def cmd_luz_lectura():
    raw = ldr_adc.read_u16()
    print("valor ADC: {:5d} / Voltaje: {:.2f} V / auto: {}".format(
        raw, raw * CONVERSION_VOLTIOS, "ON" if modo_ldr else "OFF"))


def cmd_monitor(valor):
    global monitor_ldr
    monitor_ldr = (valor == 1)
    if monitor_ldr:
        print("Monitor LDR activo. Escribe 'luz 0' para detenerlo.")
    else:
        print("Monitor LDR detenido.")


def cmd_ldr(valor):
    global modo_ldr
    if valor not in (0, 1):
        print("ldr solo acepta 1 o 0")
        return
    modo_ldr = bool(valor)
    if modo_ldr:
        cmd_luz_lectura()
        print("LDR activo: enciende bajo {} V, apaga sobre {} V".format(V_OSCURO, V_CLARO))
        revisar_ldr()
    else:
        luces["lf"] = 0
        luces["lb"] = 0
        actualizar_luces()
    print("ldr ->", valor)


def cmd_test():
    """Prueba cada motor 1 s en cada sentido para verificar el cableado."""
    print("test: traccion adelante");  traccion(4);  esperar(1); traccion(0)
    esperar(0.5)
    print("test: traccion atras");     traccion(-4); esperar(1); traccion(0)
    esperar(0.5)
    print("test: direccion izquierda"); direccion(-1); esperar(1); direccion(0)
    esperar(0.5)
    print("test: direccion derecha");   direccion(1);  esperar(1); direccion(0)
    print("test: fin")


# ---------------------------------------------------------------
# PATRONES
# ---------------------------------------------------------------
def _nivel_patron():
    return abs(nivel_actual) if nivel_actual != 0 else NIVEL_PATRON


def _vuelta(sentido):
    """Una vuelta completa (360 grados) hacia 'sentido' (1 der, -1 izq)."""
    nombre = "lr" if sentido == 1 else "ll"
    poner_luz(nombre, 1)
    direccion(sentido)
    traccion(_nivel_patron())
    esperar(TIEMPO_CIRCULO)
    poner_luz(nombre, 0)


def patron_circle():
    print("Circle")
    _vuelta(1)
    detener_todo()      # se detiene en el punto de partida


def patron_infinite():
    """8 acostado: vuelta a la derecha + vuelta a la izquierda.
    Cada lazo es un giro completo, asi vuelve al punto de partida."""
    print("Infinite")
    _vuelta(1)
    _vuelta(-1)
    detener_todo()


def patron_zigzag():
    print("ZigZag")
    traccion(_nivel_patron())
    sentido = 1
    for _ in range(REPETICIONES_ZIGZAG):
        nombre = "lr" if sentido == 1 else "ll"
        poner_luz(nombre, 1)
        direccion(sentido)
        esperar(TIEMPO_ZIGZAG)
        poner_luz(nombre, 0)
        sentido = -sentido
    detener_todo()


def patron_especial():
    """Show de luces (tipo 'auto fantastico') + avanza y retrocede."""
    print("especial")
    previas = dict(luces)
    # barrido de luces ida y vuelta
    ida_vuelta = ("lr", "lf", "lb", "ll", "lb", "lf", "lr")
    traccion(_nivel_patron())
    for _ in range(2):
        for nombre in ida_vuelta:
            for k in luces:
                luces[k] = 0
            luces[nombre] = 1
            actualizar_luces()
            esperar(0.15)
    detener_todo()
    esperar(0.3)
    # retrocede con luces traseras
    luces["lb"] = 1
    actualizar_luces()
    traccion(-_nivel_patron())
    esperar(1.5)
    detener_todo()
    # destello final y restaura estado
    for _ in range(3):
        for k in luces:
            luces[k] = 1
        actualizar_luces()
        esperar(0.2)
        for k in luces:
            luces[k] = 0
        actualizar_luces()
        esperar(0.2)
    for k in previas:
        luces[k] = previas[k]
    actualizar_luces()


# ---------------------------------------------------------------
# INTERPRETE DE COMANDOS
# ---------------------------------------------------------------
def procesar(linea):
    partes = linea.strip().split()
    if not partes:
        return
    c = partes[0].lower()

    if c == "luz":
        if len(partes) == 1:
            cmd_luz_lectura()
        elif partes[1] in ("0", "1"):
            cmd_monitor(int(partes[1]))
        else:
            print("Uso: luz | luz 1 (monitor) | luz 0 (detener)")
        return

    if c in ("circle", "infinite", "zigzag", "especial", "stop", "test"):
        if c == "circle":
            patron_circle()
        elif c == "infinite":
            patron_infinite()
        elif c == "zigzag":
            patron_zigzag()
        elif c == "especial":
            patron_especial()
        elif c == "test":
            cmd_test()
        else:
            detener_todo()
            print("stop")
        return

    if c in ("pwm", "dir", "lf", "lb", "ll", "lr", "ldr"):
        if len(partes) != 2:
            print("Uso:", c, "<valor>")
            return
        try:
            v = int(partes[1])
        except ValueError:
            print("Valor invalido:", partes[1])
            return
        if c == "pwm":
            cmd_pwm(v)
        elif c == "dir":
            cmd_dir(v)
        elif c == "ldr":
            cmd_ldr(v)
        else:
            cmd_luz(c, v)
        return

    print("Comando desconocido:", c)


def _tick_ldr(t):
    try:
        if monitor_ldr:
            cmd_luz_lectura()
        revisar_ldr()
    except Exception as e:
        print("Error en LDR:", e)


def main():
    detener_todo()
    actualizar_luces()
    # El Timer revisa el LDR mientras input() espera un comando
    Timer(-1, mode=Timer.PERIODIC, period=300, callback=_tick_ldr)
    print("Formula E CES Tec listo. Comandos: pwm dir lf lb ll lr ldr "
          "Circle Infinite ZigZag especial stop test luz")
    while True:
        linea = input("> ")
        try:
            procesar(linea)
        except Exception as e:
            detener_todo()
            print("Error:", e, "- motores detenidos")


try:
    main()
except KeyboardInterrupt:
    detener_todo()
    luces["lr"] = luces["lf"] = luces["lb"] = luces["ll"] = 0
    actualizar_luces()
    print("Detenido")