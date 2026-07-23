# -*- coding: utf-8 -*-
###############################################################################
#
#    SuperTCG
#
#    Copyright (C) 2024-TODAY SuperTCG (<https://www.supertcg.be>)
#    Author: SuperTCG
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
{
    "name": "SuperTCG Barcode Button",
    "version": "18.0.1.0.0",
    "category": "Warehouse",
    "summary": "Generates internal EAN13-style Barcode for Product.",
    "description": "Generates internal EAN13-style Barcode "
    "for Product when requested via button.",
    "author": "SuperTCG",
    "company": "SuperTCG",
    "maintainer": "SuperTCG",
    "website": "https://supertcg.be",
    "depends": ["product"],
    "images": ["static/description/banner.jpg"],
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
    "data": [
        "views/product_template_views.xml",
    ],
}
