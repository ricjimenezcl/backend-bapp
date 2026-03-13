-- Eliminar categorías antiguas
DELETE FROM service_categories;

-- Insertar nuevas categorías organizadas
INSERT INTO service_categories (name, description, parent_category, icon, is_active) VALUES
-- Hogar y Construcción
('Albañilería', 'Servicios de construcción y albañilería', 'Hogar y Construcción', 'construct', 1),
('Carpintería', 'Trabajos en madera y muebles', 'Hogar y Construcción', 'hammer', 1),
('Cerrajero domiciliario', 'Apertura e instalación de cerraduras', 'Hogar y Construcción', 'key', 1),
('Electricista domiciliario', 'Instalaciones y reparaciones eléctricas', 'Hogar y Construcción', 'flash', 1),
('Gasfitería', 'Servicios de fontanería y gas', 'Hogar y Construcción', 'water', 1),
('Pintura', 'Pintura residencial y comercial', 'Hogar y Construcción', 'color-palette', 1),
('Plomería', 'Reparaciones de tuberías y desagües', 'Hogar y Construcción', 'git-merge', 1),
('Soldadura', 'Trabajos de soldadura y metal', 'Hogar y Construcción', 'flame', 1),
('Retiro de escombros', 'Limpieza y retiro de materiales', 'Hogar y Construcción', 'trash', 1),

-- Vehículos
('Cerrajería de vehículos', 'Apertura de autos e instalación de cerraduras', 'Vehículos', 'car', 1),
('Electricidad de vehículos', 'Sistema eléctrico automotriz', 'Vehículos', 'car-battery', 1),
('Grúa', 'Servicios de grúa y transporte', 'Vehículos', 'trail-sign', 1),
('Lavado de autos', 'Lavado y detailing de vehículos', 'Vehículos', 'water', 1),
('Mecánica automotriz', 'Reparación general de autos', 'Vehículos', 'car-sport', 1),
('Mecánica de motos', 'Reparación de motocicletas', 'Vehículos', 'bicycle', 1),
('Mecánico a domicilio', 'Reparación de vehículos a domicilio', 'Vehículos', 'build', 1),
('Pintura y desabolladura', 'Pintura y reparación de carrocería', 'Vehículos', 'color-palette', 1),
('Tapicería de autos', 'Reparación de asientos y interiores', 'Vehículos', 'bed', 1),
('Vulcanización', 'Reparación y cambio de neumáticos', 'Vehículos', 'ellipse', 1),

-- Mantenimiento y Limpieza
('Aseo', 'Limpieza residencial y comercial', 'Mantenimiento y Limpieza', 'home', 1),
('Aseo y planchado', 'Limpieza y planchado de ropa', 'Mantenimiento y Limpieza', 'shirt', 1),
('Jardinería', 'Mantenimiento de jardines', 'Mantenimiento y Limpieza', 'leaf', 1),
('Arreglos florales', 'Diseño y arreglo de flores', 'Mantenimiento y Limpieza', 'flower', 1),

-- Belleza y Cuidado Personal
('Barbería', 'Cortes de cabello y afeitado', 'Belleza y Cuidado Personal', 'cut', 1),
('Depilación', 'Servicios de depilación', 'Belleza y Cuidado Personal', 'body', 1),
('Estilista', 'Estilismo y cuidado personal', 'Belleza y Cuidado Personal', 'person', 1),
('Manicura y pedicura', 'Cuidado de uñas', 'Belleza y Cuidado Personal', 'hand-left', 1),
('Peluquería', 'Cortes y tratamientos capilares', 'Belleza y Cuidado Personal', 'accessibility', 1),
('Podología', 'Cuidado de los pies', 'Belleza y Cuidado Personal', 'footsteps', 1),

-- Reparaciones y Tecnología
('Reparación de bicicletas', 'Reparación y mantenimiento de bicicletas', 'Reparaciones y Tecnología', 'bicycle', 1),
('Reparación de calzado', 'Arreglo de zapatos y calzado', 'Reparaciones y Tecnología', 'walk', 1),
('Reparación de celulares', 'Reparación de teléfonos móviles', 'Reparaciones y Tecnología', 'phone-portrait', 1),
('Reparación de computadores', 'Reparación de computadoras y notebooks', 'Reparaciones y Tecnología', 'laptop', 1),
('Reparación de electrodomésticos', 'Arreglo de electrodomésticos', 'Reparaciones y Tecnología', 'tv', 1),
('Reparación de muebles', 'Reparación y tapizado de muebles', 'Reparaciones y Tecnología', 'bed', 1),
('Costurería y sastrería', 'Arreglos de ropa y confección', 'Reparaciones y Tecnología', 'cut', 1),

-- Mascotas
('Paseo de mascotas', 'Paseo y cuidado de mascotas', 'Mascotas', 'paw', 1),
('Peluquería canina', 'Estética y cuidado de mascotas', 'Mascotas', 'paw', 1),

-- Otros Servicios
('Fletes', 'Servicios de transporte y mudanzas', 'Otros Servicios', 'car', 1);